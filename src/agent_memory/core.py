"""
Core data model — AtomicFact, FactType, and MemoryConfig.

AtomicFact is the fundamental unit of agent memory: a structured,
typed, confidence-scored fact extracted from conversation traces.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class FactType(str, Enum):
    """The 6 atomic fact types, optimized for agent conversation memory."""

    PREFERENCE = "preference"
    """User likes/dislikes, habits, preferred tools or approaches."""

    ENVIRONMENT = "environment"
    """System constraints, network limitations, hardware specs, tool availability."""

    DECISION = "decision"
    """Explicit choices made, paths selected or rejected."""

    REJECTION = "rejection_reason"
    """Why a particular option was ruled out — critical for avoiding repeat suggestions."""

    CONVENTION = "convention"
    """Recurring patterns, naming conventions, team practices, workflow habits."""

    LESSON = "lesson"
    """Mistakes, corrections, things learned the hard way."""


@dataclass
class AtomicFact:
    """
    A single atomic unit of agent memory.

    Each fact is typed, scored by confidence, and carries its own
    evidence trail and evolution history.

    Example::

        AtomicFact(
            type=FactType.PREFERENCE,
            content="User prefers CLI over GUI for system management",
            confidence=1.0,
            evidence="User: 'I prefer CLI over GUI'",
            source_date="2026-06-01",
        )
    """

    type: FactType
    """One of the 6 fact types — determines how this fact is categorized."""

    content: str
    """The atomic fact statement. Compact, specific, action-oriented."""

    confidence: float = 0.8
    """
    How sure we are this fact is true.
    - 1.0: explicitly stated by the user
    - 0.9: strongly implied by context
    - 0.8: inferred from behavior pattern
    - <0.8: speculative — not injected into system prompt
    """

    evidence: str = ""
    """The exact text from which this fact was extracted. Enables audit."""

    source_date: str = ""
    """ISO date string (YYYY-MM-DD) when this fact was observed."""

    id: str = ""
    """Content-hash based dedup key. Auto-generated if empty."""

    supersedes: str = ""
    """ID of the fact this one replaces. Enables evolution tracking."""

    created_at: float = 0.0
    """Unix timestamp of extraction. Auto-set if 0."""

    def __post_init__(self):
        # Convert string type to enum first (needed for id computation)
        if isinstance(self.type, str):
            self.type = FactType(self.type)
        if not self.id:
            self.id = self._compute_id()
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).timestamp()
        # Clamp confidence to valid range [0.0, 1.0]
        self.confidence = max(0.0, min(self.confidence, 1.0))

    def _compute_id(self) -> str:
        """Deterministic ID from type + normalized content for dedup.

        Format: {type_prefix}:{sha256_content_hash[:14]}
        The type prefix ensures the same content under different types
        is treated as different facts.
        """
        type_prefix = self.type.value[:2]  # 'pr' for preference, 'en' for environment, etc.
        normalized = re.sub(r"\s+", " ", self.content.lower().strip())
        content_hash = hashlib.sha256(normalized.encode()).hexdigest()[:14]
        return f"{type_prefix}:{content_hash}"

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "source_date": self.source_date,
            "supersedes": self.supersedes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AtomicFact":
        """Deserialize from a dict (e.g., loaded from JSONL).

        Handles legacy IDs (old format without type prefix) gracefully.
        """
        return cls(
            type=FactType(data["type"]),
            content=data["content"],
            confidence=data.get("confidence", 0.8),
            evidence=data.get("evidence", ""),
            source_date=data.get("source_date", ""),
            id=data.get("id", ""),
            supersedes=data.get("supersedes", ""),
            created_at=data.get("created_at", 0.0),
        )

    def __repr__(self) -> str:
        return (
            f"AtomicFact(type={self.type.value}, "
            f"confidence={self.confidence:.1f}, "
            f'content="{self.content[:50]}...")'
        )


@dataclass
class MemoryConfig:
    """Configuration for the memory system."""

    data_dir: str = "~/.agent/memory"
    """Directory for storing atomic fact JSONL files."""

    llm_api_key: str = ""
    """API key for the LLM used to extract facts."""

    llm_endpoint: str = "https://api.openai.com/v1/chat/completions"
    """OpenAI-compatible chat completions endpoint."""

    llm_model: str = "gpt-4o-mini"
    """Model name for fact extraction."""

    inject_threshold: float = 0.8
    """Minimum confidence for facts to be auto-injected into system prompt."""

    max_fact_length: int = 200
    """Maximum characters per atomic fact content."""

    extract_timeout: int = 120
    """Timeout in seconds for LLM extraction calls."""
