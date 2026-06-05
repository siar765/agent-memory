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


def _flush_cjk_bigrams(tokens: list[str], cjk_buf: list[str]) -> None:
    """Generate CJK bigrams from consecutive character buffer and append to tokens."""
    if len(cjk_buf) >= 2:
        for j in range(len(cjk_buf) - 1):
            tokens.append(cjk_buf[j] + cjk_buf[j + 1])


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
        buf = []          # Latin word buffer
        cjk_buf = []      # consecutive CJK character buffer
        i = 0
        while i < len(text):
            ch = text[i]
            if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f':
                if buf:
                    tokens.append(''.join(buf))
                    buf = []
                tokens.append(ch)
                cjk_buf.append(ch)
            elif ch.isalnum():
                _flush_cjk_bigrams(tokens, cjk_buf)
                cjk_buf = []
                buf.append(ch)
            else:
                if buf:
                    tokens.append(''.join(buf))
                    buf = []
                _flush_cjk_bigrams(tokens, cjk_buf)
                cjk_buf = []
            i += 1
        if buf:
            tokens.append(''.join(buf))
        _flush_cjk_bigrams(tokens, cjk_buf)
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
        active_only: bool = True,
        limit: int = 10,
        min_confidence: float = 0.0,
        use_bm25: bool = True,
        use_confidence_decay: bool = True,
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
            active_only: Only return active facts (default: True).
            limit: Maximum results to return.
            min_confidence: Minimum confidence threshold.
            use_bm25: Enable BM25 term-frequency ranking (default: True).
            use_confidence_decay: Apply time-based decay to confidence (default: True).

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

        # Apply confidence filter (with optional decay)
        half_life = self.store.config.confidence_half_life_days if use_confidence_decay else 0.0
        if min_confidence:
            facts = [
                f for f in facts
                if _effective_confidence(f, half_life) >= min_confidence
            ]

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
                    + _effective_confidence(x[0], half_life) * 0.2
                    + _recency_score(x[0]) * 0.15
                    + _frequency_score(x[0]) * 0.1
                    + _type_priority_score(x[0], query) * 0.1
                ), reverse=True)
                facts = [r[0] for r in ranked[:limit]]
            else:
                # Search with query but BM25 found nothing relevant — return empty
                return []
        else:
            # Simple sort: effective confidence first, then newest
            facts.sort(key=lambda f: (
                -_effective_confidence(f, half_life),
                -f.created_at
            ))
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
        include_global: bool = False,
        use_confidence_decay: bool = True,
    ) -> str:
        """Generate a compact summary for system prompt injection.

        Active/superseded computation is done on the **full** fact set
        BEFORE confidence/date filtering, ensuring superseded facts
        don't leak through when the superseding fact happens to be
        filtered out.

        When a project is specified without an explicit ``scope`` restriction,
        global preferences are auto-merged — so ``inject --project blog``
        gives you project context + personal preferences in one shot.
        Use ``--scope project --project blog`` to exclude global facts.

        Args:
            limit: Maximum facts to include.
            min_confidence: Minimum confidence (default 0.8).
            date_from: Only include facts from this date onwards.
            query: Optional task context — facts are ranked by relevance to this query.
            active_only: Skip superseded/proposed/wrong/archived facts (default: True).
            scope: Filter by scope (``global`` / ``project``).
            project: Filter by project name.
            include_global: When True and scope/project is set, also include global facts.
            use_confidence_decay: Apply time-based decay to confidence (default: True).

        Returns:
            Formatted markdown string for system prompt injection, or empty string.
        """
        # Auto-include global when project is set but scope is not explicitly restricted.
        # This makes `inject --project blog` give you project + global preferences
        # without needing --include-global. Use --scope project to exclude global.
        should_include_global = (project and not scope) or include_global

        if should_include_global and project:
            project_facts = self.store.load(
                date_from=date_from,
                scope="project",
                project=project,
            )
            global_facts = self.store.load(
                date_from=date_from,
                scope="global",
            )
            all_facts = project_facts + global_facts
        else:
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
            all_facts = [
                f for f in all_facts
                if f.status == "active"
                and f.id not in superseded_ids
            ]

        if not all_facts:
            return ""

        # Step 4: Now apply confidence filter (with optional decay)
        half_life = self.store.config.confidence_half_life_days if use_confidence_decay else 0.0
        facts = [f for f in all_facts if _effective_confidence(f, half_life) >= min_confidence]

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
                    + _effective_confidence(x[0], half_life) * 0.2
                    + _recency_score(x[0]) * 0.15
                    + _frequency_score(x[0]) * 0.1
                    + _type_priority_score(x[0], query) * 0.1
                ), reverse=True)
                facts = [r[0] for r in ranked[:limit]]
            else:
                facts.sort(key=lambda f: (
                    -_effective_confidence(f, half_life),
                    -f.created_at
                ))
                facts = facts[:limit]
        else:
            facts.sort(key=lambda f: (
                -_effective_confidence(f, half_life),
                -f.created_at
            ))
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
        summary += f"*({len(facts)} active facts, threshold ≥{int(min_confidence * 100)}% confidence, half-life {int(half_life)}d)*\n"

        return summary

    def by_type(self, fact_type: str, limit: int = 20) -> list[AtomicFact]:
        """Quick lookup: get facts of a specific type."""
        return self.search(fact_type=fact_type, limit=limit, use_bm25=False)

    def _profile_topic_groups(self, facts: list[AtomicFact]) -> tuple[dict[str, list[AtomicFact]], list[AtomicFact]]:
        """Assign preference facts to topic groups by keyword matching.

        Returns:
            (assigned: dict[topic_name -> facts], unassigned: list[facts])
        """
        topics = [
            {"name": "UI Theme",
             "keywords": ["dark mode", "light mode", "theme", "dark", "light",
                          "白天", "黑夜", "主题", "深色"]},
            {"name": "Interface",
             "keywords": ["cli", "gui", "terminal", "command line", "command-line",
                          "命令行", "界面", "tui"]},
            {"name": "Editor & IDE",
             "keywords": ["vim", "neovim", "nvim", "vs code", "vscode",
                          "emacs", "editor", "ide", "编辑器", "ide"]},
            {"name": "Programming Language",
             "keywords": ["python", "rust", "go", "golang", "javascript",
                          "typescript", "java", "c++", "c#", "ruby", "php",
                          "语言", "编程"]},
            {"name": "Communication",
             "keywords": ["concise", "brief", "verbose", "detailed", "short",
                          "简洁", "详细", "长", "短", "废话", "啰嗦"]},
            {"name": "Dietary",
             "keywords": ["coffee", "tea", "drink", "americano", "latte",
                          "cappuccino", "ruixing", "瑞幸", "咖啡", "茶",
                          "美式", "黑咖啡", "不加糖", "无糖", "纯"]},
            {"name": "OS & Platform",
             "keywords": ["linux", "macos", "windows", "debian", "ubuntu",
                          "arch", "fedora", "系统", "操作系统"]},
            {"name": "Deployment",
             "keywords": ["docker", "kubernetes", "k8s", "container",
                          "部署", "容器"]},
            {"name": "Cost & Licensing",
             "keywords": ["free", "open source", "paid", "cost", "cheap",
                          "expensive", "免费", "开源", "付费", "贵", "便宜",
                          "白嫖", "bug 价"]},
            {"name": "Testing",
             "keywords": ["test", "tdd", "unit test", "testing", "测试",
                          "单元测试"]},
        ]

        assigned: dict[str, list[AtomicFact]] = {}
        unassigned: list[AtomicFact] = []

        for fact in facts:
            content_lower = fact.content.lower()
            matched = False
            for t in topics:
                if any(kw in content_lower for kw in t["keywords"]):
                    assigned.setdefault(t["name"], []).append(fact)
                    matched = True
                    break
            if not matched:
                unassigned.append(fact)

        return assigned, unassigned, topics

    def summarize(
        self,
        topic: str = "",
        min_confidence: float = 0.7,
        fmt: str = "markdown",
    ) -> str:
        """Generate a readable user profile from preference facts.

        Groups preference facts by detected topic and generates
        natural-language summary sentences — pure rule-based, zero dependencies.

        Args:
            topic: Filter to a specific topic (case-insensitive keyword match).
            min_confidence: Minimum confidence threshold (default 0.7).
            fmt: Output format — ``markdown`` or ``text``.

        Returns:
            Formatted profile string, or empty string if no preferences found.
        """
        facts = self.store.load(fact_type="preference", active_only=True)
        if not facts:
            return ""

        facts = [f for f in facts if f.confidence >= min_confidence]
        if not facts:
            return ""

        facts.sort(key=lambda f: (-f.confidence, -f.created_at))
        assigned, unassigned, topics = self._profile_topic_groups(facts)

        if topic:
            topic_lower = topic.lower()
            matched_name = None
            for t in topics:
                if topic_lower in t["name"].lower():
                    matched_name = t["name"]
                    break
            if matched_name:
                assigned = {matched_name: assigned.get(matched_name, [])}
                unassigned = []
            else:
                # Search all facts (assigned + unassigned) by content keyword
                topic_keywords = topic_lower.split()
                all_facts = list(unassigned)
                for g in assigned.values():
                    all_facts.extend(g)
                filtered = [
                    f for f in all_facts
                    if any(kw in f.content.lower() for kw in topic_keywords)
                ]
                assigned = {}
                unassigned = filtered

        lines: list[str] = []
        if fmt == "text":
            lines.append("User Profile")
            lines.append("=" * 40)
        else:
            lines.append("## User Profile")

        for topic_name in [t["name"] for t in topics]:
            group = assigned.get(topic_name, [])
            if not group:
                continue

            if fmt == "text":
                lines.append(f"\n{topic_name}:")
            else:
                lines.append(f"\n**{topic_name}**")

            high = [f for f in group if f.confidence >= 0.9]
            medium = [f for f in group if f.confidence < 0.9]

            if high:
                text = ". ".join(
                    f.content.rstrip(".") for f in high[:3]
                ) + "."
                lines.append(_fmt_bullet(text, fmt))
            if medium:
                text = ". ".join(
                    f.content.rstrip(".") for f in medium[:2]
                ) + "."
                lines.append(_fmt_bullet(text, fmt))

        if unassigned:
            if fmt == "text":
                lines.append("\nOther:")
            else:
                lines.append("\n**Other**")
            for f in unassigned[:5]:
                lines.append(
                    _fmt_bullet(f"{f.content} ({int(f.confidence * 100)}%)", fmt)
                )

        if len(lines) <= 2:
            return ""

        summary = "\n".join(lines) + "\n"
        if fmt == "text":
            summary += f"\n{'=' * 40}\n"
            summary += f"Based on {len(facts)} preferences, threshold \u2265{int(min_confidence * 100)}%\n"
        else:
            summary += f"\n*({len(facts)} preferences, \u2265{int(min_confidence * 100)}% confidence)*\n"

        return summary

    def history(self, fact_id: str = "",
                query: str = "", limit: int = 5) -> str:
        """Trace the evolution history of a fact or set of facts.

        Walks the ``supersedes`` chain forward and backward to show
        how a fact evolved over time. Can start from a specific ID
        or search by keyword.

        Args:
            fact_id: Specific fact ID to trace.
            query: Search keyword to find facts first.
            limit: Max results when searching by query (default 5).

        Returns:
            Formatted evolution timeline string, or empty if not found.
        """
        # Load all facts to build lookup maps
        all_facts = self.store.load(active_only=False)
        if not all_facts:
            return "[agent-memory] No facts in storage"

        by_id: dict[str, AtomicFact] = {}
        by_supersedes: dict[str, list[AtomicFact]] = {}  # old_id -> [newer facts]
        for f in all_facts:
            by_id[f.id] = f
            if f.supersedes:
                by_supersedes.setdefault(f.supersedes, []).append(f)

        # ── Find starting facts ────────────────────────────────────────
        start_ids: list[str] = []

        if fact_id:
            if fact_id not in by_id:
                return f"[agent-memory] Fact not found: {fact_id}"
            start_ids = [fact_id]
        elif query:
            ql = query.lower()
            matches = [f for f in all_facts if ql in f.content.lower()]
            if not matches:
                return f"[agent-memory] No facts matching: {query}"
            # Prefer active, then high confidence
            matches.sort(key=lambda f: (f.status != "active", -f.confidence))
            start_ids = [f.id for f in matches[:limit]]

        # ── Walk chain backward (find root) ───────────────────────────
        # For each start ID, walk backwards to the oldest version
        def walk_backward(fid: str, visited: set[str]) -> list[AtomicFact]:
            chain = []
            current = by_id.get(fid)
            while current:
                if current.id in visited:
                    break  # cycle detected
                visited.add(current.id)
                chain.append(current)
                # Try finding what this fact supersedes
                ss = current.supersedes
                if ss and ss in by_id:
                    current = by_id[ss]
                else:
                    current = None
            chain.reverse()  # oldest first
            return chain

        visited: set[str] = set()
        all_chains: list[list[AtomicFact]] = []

        for sid in start_ids:
            if sid in visited:
                continue
            chain = walk_backward(sid, visited)

            # Also walk forward (find newer versions)
            def walk_forward(facts: list[AtomicFact], forward_visited: set[str]) -> list[AtomicFact]:
                # Start from the root (first in reversed chain)
                current_id = facts[-1].id
                while True:
                    if current_id in forward_visited:
                        break
                    forward_visited.add(current_id)
                    successors = by_supersedes.get(current_id, [])
                    if not successors:
                        break
                    # If multiple successors, only follow the first
                    succ = successors[0]
                    if succ.id not in by_id:
                        break
                    facts.append(succ)
                    current_id = succ.id
                return facts

            forward_visited: set[str] = set()
            chain = walk_forward(chain, forward_visited)

            all_chains.append(chain)

        # ── Format output ──────────────────────────────────────────────
        lines = ["## Evolution History"]

        for chain in all_chains:
            lines.append("")
            for i, fact in enumerate(chain):
                if i == 0 and len(chain) > 1:
                    marker = "🟢" if fact.status == "active" else "🔴"
                    label = "origin"
                elif i == len(chain) - 1 and len(chain) > 1:
                    marker = "🟢" if fact.status == "active" else "🔴"
                    label = "current"
                else:
                    marker = "🟡" if fact.status == "active" else "🔴"
                    label = "v" + str(i)

                status_tag = f"[{fact.status}]" if fact.status != "active" else ""
                lines.append(
                    f"{marker} **{label}** — "
                    f"{fact.type.value} | {int(fact.confidence * 100)}% "
                    f"{status_tag}"
                )
                lines.append(f"   `{fact.content[:100]}`")
                if fact.evidence and fact.evidence != "[REDACTED]":
                    lines.append(f"   ↳ {fact.evidence[:80]}")

        if not all_chains:
            return ""

        lines.append("")
        lines.append(f"*Traced {len(all_chains)} chain(s) from {len(all_facts)} total facts*")

        return "\n".join(lines)


# ==============================================================================
# Scoring helpers
# ==============================================================================


def _fmt_bullet(text: str, fmt: str) -> str:
    """Format a single bullet item."""
    prefix = "" if fmt == "text" else "- "
    return f"{prefix}{text}"





def _recency_score(fact: AtomicFact) -> float:
    """Score 0.0-1.0 based on how recent a fact is (within last 90 days)."""
    age_days = (time.time() - fact.created_at) / 86400
    return max(0.0, 1.0 - age_days / 90.0)


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
