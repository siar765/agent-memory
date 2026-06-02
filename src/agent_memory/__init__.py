"""
agent-memory: Structured atomic fact memory for LLM agents.

Extract typed, confidence-scored, evolution-tracked memory entries
from conversation traces. Designed for agents that need to remember
what matters and forget what doesn't.
"""

from .core import AtomicFact, FactType, MemoryConfig
from .extractor import FactExtractor
from .storage import MemoryStore
from .search import MemorySearch

__version__ = "0.1.0"
__all__ = [
    "AtomicFact",
    "FactType",
    "MemoryConfig",
    "FactExtractor",
    "MemoryStore",
    "MemorySearch",
]
