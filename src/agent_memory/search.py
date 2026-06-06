"""
Search and inject — retrieve relevant facts and format them for system prompts.
"""

from __future__ import annotations

import time
from typing import Optional

from .core import AtomicFact, FactType, MemoryConfig
from .storage import MemoryStore


# ── Scoring helpers ──────────────────────────────────────────────────

def _effective_confidence(fact: AtomicFact, half_life_days: float = 30.0) -> float:
    """Apply time-based decay to a fact's raw confidence.

    Formula:  effective = raw * (0.5) ^ (age_days / half_life_days)

    A fact with raw confidence 0.9 and half-life 30d:
      - Day 0:   0.900
      - Day 30:  0.450  (one half-life)
      - Day 60:  0.225  (two half-lives)
      - Day 90:  0.112  (three half-lives)

    Set half_life_days to 0 to disable decay (returns raw confidence).
    """
    if half_life_days <= 0:
        return fact.confidence
    age_days = (time.time() - fact.created_at) / 86400
    if age_days <= 0:
        return fact.confidence
    decay = 0.5 ** (age_days / half_life_days)
    return fact.confidence * decay


class MemorySearch:
    """Search and retrieve atomic facts with type/date/keyword filters."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def search(
        self,
        query: str = "",
        fact_type: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 10,
        min_confidence: float = 0.0,
        use_confidence_decay: bool = True,
    ) -> list[AtomicFact]:
        """Search facts by keyword, type, date range, and confidence.

        Args:
            query: Keyword to match in fact content (case-insensitive).
            fact_type: Filter by fact type string.
            date_from: Earliest date (YYYY-MM-DD).
            date_to: Latest date (YYYY-MM-DD).
            limit: Maximum results to return.
            min_confidence: Minimum confidence threshold.
            use_confidence_decay: Apply time-based decay to confidence.

        Returns:
            Matched facts sorted by confidence (high to low), then by date (newest first).
        """
        facts = self.store.load(
            date_from=date_from,
            date_to=date_to,
            fact_type=fact_type,
        )

        # Apply keyword filter
        if query:
            query_lower = query.lower()
            facts = [f for f in facts if query_lower in f.content.lower()]

        # Apply confidence filter (with optional decay)
        half_life = self.store.config.confidence_half_life_days if use_confidence_decay else 0.0
        if min_confidence:
            facts = [
                f for f in facts
                if _effective_confidence(f, half_life) >= min_confidence
            ]
        if not facts:
            return []

        # Sort: by effective confidence (decayed), then newest
        facts.sort(key=lambda f: (
            -_effective_confidence(f, half_life),
            -f.created_at
        ))

        return facts[:limit]

    def inject_summary(
        self,
        limit: int = 15,
        min_confidence: float = 0.8,
        date_from: str = "",
        query: str = "",
        active_only: bool = True,
        scope: str = "",
        project: str = "",
        include_global: bool = False,
        use_confidence_decay: bool = True,
    ) -> str:
        """Generate a compact summary for system prompt injection.

        Only includes high-confidence facts. Format is optimized for
        LLM context window efficiency.

        Args:
            limit: Maximum facts to include.
            min_confidence: Minimum confidence (default 0.8).
            date_from: Only include facts from this date onwards.
            query: Optional keyword filter.
            active_only: Only include active (non-superseded) facts.
            scope: Filter by scope.
            project: Filter by project.
            include_global: Also include global-scope facts.
            use_confidence_decay: Apply time-based decay to confidence.

        Returns:
            Formatted markdown string for system prompt injection.
        """
        facts = self.store.load(date_from=date_from)

        # Filter and sort
        half_life = self.store.config.confidence_half_life_days if use_confidence_decay else 0.0
        facts = [
            f for f in facts
            if _effective_confidence(f, half_life) >= min_confidence
        ]
        facts.sort(key=lambda f: (
            -_effective_confidence(f, half_life),
            -f.created_at
        ))
        facts = facts[:limit]

        if not facts:
            return ""

        lines = ["## Atomic Fact Summary"]
        for f in facts:
            emoji = {
                "preference": "💡",
                "environment": "🔧",
                "decision": "✅",
                "rejection_reason": "❌",
                "convention": "📐",
                "lesson": "📝",
            }.get(f.type.value, "•")
            confidence_str = f"{int(f.confidence * 100)}%"
            date_str = f.source_date or ""
            lines.append(f"- {emoji} [{confidence_str}] {f.content}")

        summary = "\n".join(lines) + "\n"
        summary += f"*({len(facts)} active facts, threshold ≥{int(min_confidence * 100)}% confidence, half-life {int(half_life)}d)*\n"
        return summary

    def by_type(self, fact_type: str, limit: int = 20) -> list[AtomicFact]:
        """Quick lookup: get facts of a specific type.

        Args:
            fact_type: Fact type string (e.g., "preference", "environment").
            limit: Maximum results.

        Returns:
            Facts of the given type, newest first.
        """
        return self.search(fact_type=fact_type, limit=limit)
