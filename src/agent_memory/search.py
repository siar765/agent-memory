"""
Search and inject — retrieve relevant facts and format them for system prompts.
"""

from __future__ import annotations

from typing import Optional

from .core import AtomicFact, FactType, MemoryConfig
from .storage import MemoryStore


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
    ) -> list[AtomicFact]:
        """Search facts by keyword, type, date range, and confidence.

        Args:
            query: Keyword to match in fact content (case-insensitive).
            fact_type: Filter by fact type string.
            date_from: Earliest date (YYYY-MM-DD).
            date_to: Latest date (YYYY-MM-DD).
            limit: Maximum results to return.
            min_confidence: Minimum confidence threshold.

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

        # Apply confidence filter
        if min_confidence:
            facts = [f for f in facts if f.confidence >= min_confidence]

        # Sort: high confidence first, then newest
        facts.sort(key=lambda f: (-f.confidence, -f.created_at))

        return facts[:limit]

    def inject_summary(
        self,
        limit: int = 15,
        min_confidence: float = 0.8,
        date_from: str = "",
    ) -> str:
        """Generate a compact summary for system prompt injection.

        Only includes high-confidence facts. Format is optimized for
        LLM context window efficiency.

        Args:
            limit: Maximum facts to include.
            min_confidence: Minimum confidence (default 0.8).
            date_from: Only include facts from this date onwards.

        Returns:
            Formatted markdown string for system prompt injection.
        """
        facts = self.store.load(date_from=date_from)

        # Filter and sort
        facts = [f for f in facts if f.confidence >= min_confidence]
        facts.sort(key=lambda f: (-f.confidence, -f.created_at))
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

        return "\n".join(lines) + "\n"

    def by_type(self, fact_type: str, limit: int = 20) -> list[AtomicFact]:
        """Quick lookup: get facts of a specific type.

        Args:
            fact_type: Fact type string (e.g., "preference", "environment").
            limit: Maximum results.

        Returns:
            Facts of the given type, newest first.
        """
        return self.search(fact_type=fact_type, limit=limit)
