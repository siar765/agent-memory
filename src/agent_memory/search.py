"""
Search and inject — retrieve relevant facts and format them for system prompts.

Provides BM25 term-frequency search (zero-dependency pure Python implementation)
alongside keyword, type, date, scope, project, status, and confidence filters.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from typing import Optional

from .core import AtomicFact, FactType, MemoryConfig
from .storage import MemoryStore


# ==============================================================================
# Pure-Python BM25 implementation (zero external dependencies)
# ==============================================================================


class _BM25:
    """BM25 ranking for term-frequency-aware search.

    Pure Python implementation using only math and collections.
    k1 = 1.5, b = 0.75 are standard Okapi BM25 parameters.
    """

    def __init__(self, corpus: list[str]):
        self.k1 = 1.5
        self.b = 0.75
        self.corpus = corpus
        self.n_docs = len(corpus)
        self.avg_dl = sum(len(self._tokenize(d)) for d in corpus) / max(self.n_docs, 1)

        # Build document term frequencies
        self.doc_tfs: list[Counter] = [Counter(self._tokenize(d)) for d in corpus]

        # Build inverse document frequencies
        self.idf: dict[str, float] = {}
        for doc in self.doc_tfs:
            for term in doc:
                self.idf[term] = self.idf.get(term, 0.0)

        n_docs_float = float(self.n_docs)
        for term in self.idf:
            df = sum(1 for doc_tf in self.doc_tfs if term in doc_tf)
            self.idf[term] = math.log((n_docs_float - df + 0.5) / (df + 0.5) + 1.0)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize with CJK support — zero external dependencies.

        Splits on whitespace/punctuation for Latin text, and extracts
        individual CJK characters plus bigrams for Chinese/Japanese/Korean.
        """
        text = text.lower()
        tokens = []
        i = 0
        buf = []
        while i < len(text):
            ch = text[i]
            if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f':
                # Flush any Latin buffer
                if buf:
                    tokens.append(''.join(buf))
                    buf = []
                tokens.append(ch)
            elif ch.isalnum():
                buf.append(ch)
            else:
                if buf:
                    tokens.append(''.join(buf))
                    buf = []
                if ch in (' ', '\t', '\n', '\r'):
                    pass  # skip whitespace
                # skip punctuation
            i += 1
        if buf:
            tokens.append(''.join(buf))
        return tokens

    def score(self, query_terms: list[str], doc_idx: int) -> float:
        """BM25 score for a single document."""
        doc_tf = self.doc_tfs[doc_idx]
        doc_len = sum(doc_tf.values())
        score = 0.0
        for term in query_terms:
            if term not in self.idf:
                continue
            tf = doc_tf.get(term, 0)
            numerator = tf * (self.k1 + 1.0)
            denominator = tf + self.k1 * (1.0 - self.b + self.b * doc_len / self.avg_dl)
            score += self.idf[term] * numerator / denominator
        return score

    def search(self, query: str, top_k: int = 50) -> list[tuple[int, float]]:
        """Return list of (doc_index, score) sorted by relevance."""
        query_terms = self._tokenize(query)
        if not query_terms or not self.corpus:
            return []

        scored = [(i, self.score(query_terms, i)) for i in range(self.n_docs)]
        scored.sort(key=lambda x: -x[1])
        return [(i, s) for i, s in scored if s > 0][:top_k]


# ==============================================================================
# TYPE PRIORITY — used in ranking when a query suggests a task type
# ==============================================================================

# Priority boost matrix: if query matches type keywords, boost that type
_TYPE_PRIORITY_KEYWORDS = {
    "preference": ["like", "prefer", "want", "dislike", "hate", "讨厌", "喜欢", "想要"],
    "environment": ["server", "network", "system", "config", "setup", "env", "环境", "系统"],
    "decision": ["chose", "decided", "selected", "choose", "which", "决定", "选择"],
    "rejection_reason": ["why not", "rejected", "avoid", "ruled out", "不要", "为什么"],
    "convention": ["how", "always", "standard", "convention", "习惯", "规则"],
    "lesson": ["learn", "mistake", "broke", "error", "教训", "坑", "错了"],
}


def _estimate_task_type(query: str) -> str | None:
    """Guess what fact type is most relevant to a query."""
    q = query.lower()
    best_type = None
    best_score = 0
    for fact_type, keywords in _TYPE_PRIORITY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in q)
        if score > best_score:
            best_score = score
            best_type = fact_type
    return best_type


# ==============================================================================
# MAIN SEARCH CLASS
# ==============================================================================


class MemorySearch:
    """Search and retrieve atomic facts with BM25 + type/date/scope/project/confidence filters."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def search(
        self,
        query: str = "",
        fact_type: str = "",
        date_from: str = "",
        date_to: str = "",
        scope: str = "",
        project: str = "",
        status: str = "",
        active_only: bool = False,
        limit: int = 10,
        min_confidence: float = 0.0,
        use_bm25: bool = True,
    ) -> list[AtomicFact]:
        """Search facts with optional BM25 ranking.

        NOTE: BM25 now runs on ALL loaded facts — no substring pre-filter
        that would truncate the candidate set. CJK tokenization handles
        Chinese/Japanese queries without external dependencies.

        Args:
            query: Search keywords (used for BM25 ranking when enabled).
            fact_type: Filter by fact type string.
            date_from: Earliest date (YYYY-MM-DD).
            date_to: Latest date (YYYY-MM-DD).
            scope: Filter by scope (``global`` / ``project``).
            project: Filter by project name.
            status: Filter by status string.
            active_only: Shortcut for ``status="active"``.
            limit: Maximum results to return.
            min_confidence: Minimum confidence threshold.
            use_bm25: Enable BM25 term-frequency ranking (default: True).

        Returns:
            Matched facts sorted by relevance.
        """
        facts = self.store.load(
            date_from=date_from,
            date_to=date_to,
            fact_type=fact_type,
            scope=scope,
            project=project,
            status=status,
            active_only=active_only,
        )

        if not facts:
            return []

        # Apply confidence filter
        if min_confidence:
            facts = [f for f in facts if f.confidence >= min_confidence]

        if not facts:
            return []

        # ---- BM25 ranking on FULL candidate set ----
        # No substring pre-filter — BM25 runs on all matching facts.
        if use_bm25 and query and len(facts) > 1:
            corpus = [f.content + " " + f.evidence for f in facts]
            bm25 = _BM25(corpus)
            scored_indices = bm25.search(query, top_k=limit * 2)
            if scored_indices:
                ranked = [(facts[i], s) for i, s in scored_indices]
                # Merge BM25 score with confidence and recency
                ranked.sort(key=lambda x: (
                    x[1] * 0.45
                    + x[0].confidence * 0.2
                    + _recency_score(x[0]) * 0.15
                    + _frequency_score(x[0]) * 0.1
                    + _type_priority_score(x[0], query) * 0.1
                ), reverse=True)
                facts = [r[0] for r in ranked[:limit]]
            else:
                # Fallback: sort by confidence then recency
                facts.sort(key=lambda f: (-f.confidence, -f.created_at))
                facts = facts[:limit]
        else:
            # Simple sort: confidence first, then newest
            facts.sort(key=lambda f: (-f.confidence, -f.created_at))
            facts = facts[:limit]

        return facts

    def inject_summary(
        self,
        limit: int = 15,
        min_confidence: float = 0.8,
        date_from: str = "",
        query: str = "",
        active_only: bool = True,
        scope: str = "",
        project: str = "",
    ) -> str:
        """Generate a compact summary for system prompt injection.

        Active/superseded computation is done on the **full** fact set
        BEFORE confidence/date filtering, ensuring superseded facts
        don't leak through when the superseding fact happens to be
        filtered out.

        Args:
            limit: Maximum facts to include.
            min_confidence: Minimum confidence (default 0.8).
            date_from: Only include facts from this date onwards.
            query: Optional task context — facts are ranked by relevance to this query.
            active_only: Skip facts that have been superseded (default: True).
            scope: Filter by scope (``global`` / ``project``).
            project: Filter by project name.

        Returns:
            Formatted markdown string for system prompt injection, or empty string.
        """
        # Step 1: Load ALL facts (no confidence/date filter yet)
        all_facts = self.store.load(
            date_from=date_from,
            scope=scope,
            project=project,
        )

        if not all_facts:
            return ""

        # Step 2: Compute superseded IDs on the FULL set
        superseded_ids: set[str] = set()
        if active_only:
            superseded_ids = {f.supersedes for f in all_facts if f.supersedes}

        # Step 3: Filter active (based on full-set computation)
        if active_only:
            all_facts = [f for f in all_facts if f.id not in superseded_ids]

        if not all_facts:
            return ""

        # Step 4: Now apply confidence filter
        facts = [f for f in all_facts if f.confidence >= min_confidence]

        if not facts:
            return ""

        # Step 5: Rank by relevance, confidence, recency, frequency, and type priority
        if query:
            corpus = [f.content + " " + f.evidence for f in facts]
            bm25 = _BM25(corpus) if len(facts) > 1 else None
            scored_indices = bm25.search(query, top_k=limit * 2) if bm25 else []
            if scored_indices:
                ranked = [(facts[i], s) for i, s in scored_indices]
                ranked.sort(key=lambda x: (
                    x[1] * 0.45
                    + x[0].confidence * 0.2
                    + _recency_score(x[0]) * 0.15
                    + _frequency_score(x[0]) * 0.1
                    + _type_priority_score(x[0], query) * 0.1
                ), reverse=True)
                facts = [r[0] for r in ranked[:limit]]
            else:
                facts.sort(key=lambda f: (-f.confidence, -f.created_at))
                facts = facts[:limit]
        else:
            facts.sort(key=lambda f: (-f.confidence, -f.created_at))
            facts = facts[:limit]

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
            tag = f"[{f.scope}/{f.project or '*'}] [{f.type.value}]"
            lines.append(f"- {emoji} {tag} {confidence_str} | {f.content}")

        summary = "\n".join(lines) + "\n"
        summary += f"*({len(facts)} active facts, threshold ≥{int(min_confidence * 100)}% confidence)*\n"

        return summary

    def by_type(self, fact_type: str, limit: int = 20) -> list[AtomicFact]:
        """Quick lookup: get facts of a specific type."""
        return self.search(fact_type=fact_type, limit=limit, use_bm25=False)


# ==============================================================================
# Scoring helpers
# ==============================================================================


def _recency_score(fact: AtomicFact) -> float:
    """Score 0.0-1.0 based on how recent a fact is (within last 90 days)."""
    age_days = (time.time() - fact.created_at) / 86400
    return max(0.0, 1.0 - age_days / 90.0)


def _frequency_score(fact: AtomicFact) -> float:
    """Score based on how many times this fact type appears (repeat = important).

    Uses a fixed neutral score for simplicity. Can be extended to count
    per-type frequency across the entire fact store.
    """
    return 0.5


def _type_priority_score(fact: AtomicFact, query: str) -> float:
    """Boost score if fact type matches the query's task type."""
    task_type = _estimate_task_type(query)
    if task_type and fact.type.value == task_type:
        return 1.0
    return 0.0
