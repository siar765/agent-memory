"""Tests for agent_memory.search — MemorySearch and inject_summary."""

import tempfile

from agent_memory.core import AtomicFact, FactType, MemoryConfig
from agent_memory.storage import MemoryStore
from agent_memory.search import MemorySearch, _BM25


def _make_search(tmp_dir: str) -> tuple[MemorySearch, MemoryStore]:
    config = MemoryConfig(data_dir=tmp_dir)
    store = MemoryStore(config)
    return MemorySearch(store), store


def _seed_data(store: MemoryStore):
    facts = [
        AtomicFact(type=FactType.PREFERENCE, content="User prefers CLI over GUI", confidence=1.0, source_date="2026-06-01"),
        AtomicFact(type=FactType.ENVIRONMENT, content="Docker port 443 is blocked", confidence=1.0, source_date="2026-06-01"),
        AtomicFact(type=FactType.DECISION, content="Chose PostgreSQL over MySQL", confidence=0.95, source_date="2026-06-01"),
        AtomicFact(type=FactType.REJECTION, content="Rejected MongoDB — too complex for single-user", confidence=0.9, source_date="2026-06-02"),
        AtomicFact(type=FactType.CONVENTION, content="Projects use MIT license by default", confidence=0.85, source_date="2026-06-02"),
        AtomicFact(type=FactType.LESSON, content="patch tool double-escapes JSON — use write_file instead", confidence=1.0, source_date="2026-06-03"),
        AtomicFact(type=FactType.PREFERENCE, content="User drinks Ruixing americano black", confidence=0.9, source_date="2026-06-02"),
        # Low confidence fact — should be filtered out in inject
        AtomicFact(type=FactType.PREFERENCE, content="User might like tea", confidence=0.6, source_date="2026-06-01"),
    ]
    store.save(facts)


class TestMemorySearch:
    def test_search_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, _ = _make_search(tmp)
            assert searcher.search(query="anything") == []

    def test_search_by_keyword(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            results = searcher.search(query="CLI")
            assert len(results) == 1
            assert "CLI" in results[0].content

    def test_search_by_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            results = searcher.search(fact_type="preference")
            assert len(results) == 3  # CLI preference + Ruixing + low-confidence tea
            assert all(f.type == FactType.PREFERENCE for f in results)

    def test_search_by_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            results = searcher.search(min_confidence=0.95)
            assert len(results) >= 2
            assert all(f.confidence >= 0.95 for f in results)

    def test_search_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            results = searcher.search(limit=2)
            assert len(results) <= 2

    def test_search_sorts_by_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            results = searcher.search()  # all facts
            for i in range(len(results) - 1):
                # First by confidence desc, then by date desc
                assert results[i].confidence >= results[i + 1].confidence

    def test_case_insensitive_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            results = searcher.search(query="cli")
            assert len(results) == 1

    def test_by_type_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            results = searcher.by_type("environment")
            assert len(results) == 1
            assert results[0].type == FactType.ENVIRONMENT


class TestInjectSummary:
    def test_inject_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, _ = _make_search(tmp)
            assert searcher.inject_summary() == ""

    def test_inject_filters_low_confidence(self):
        """Facts below 0.8 should not appear in inject summary."""
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            summary = searcher.inject_summary()
            assert "might like tea" not in summary  # 0.6 confidence
            assert "CLI" in summary  # 1.0 confidence

    def test_inject_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            summary = searcher.inject_summary(limit=2)
            lines = [l for l in summary.split("\n") if l.startswith("-")]
            assert len(lines) <= 2

    def test_inject_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            summary = searcher.inject_summary()
            assert summary.startswith("## Atomic Fact Summary")
            lines = summary.split("\n")
            assert any(l.startswith("- ") for l in lines)

    def test_inject_excludes_non_active_status(self):
        """inject_summary(active_only=True) should exclude wrong/archived/proposed facts."""
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            store.save([
                AtomicFact(type=FactType.PREFERENCE, content="Active preference", confidence=1.0, status="active"),
                AtomicFact(type=FactType.PREFERENCE, content="Wrong fact", confidence=1.0, status="wrong"),
                AtomicFact(type=FactType.PREFERENCE, content="Archived fact", confidence=1.0, status="archived"),
                AtomicFact(type=FactType.CONVENTION, content="Proposed pattern", confidence=0.6, status="proposed"),
            ])
            summary = searcher.inject_summary(active_only=True)
            assert "Active preference" in summary
            assert "Wrong fact" not in summary
            assert "Archived fact" not in summary
            assert "Proposed pattern" not in summary

    def test_inject_with_all_includes_proposed(self):
        """inject_summary(active_only=False) should include all statuses."""
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            store.save([
                AtomicFact(type=FactType.CONVENTION, content="Proposed pattern", confidence=0.9, status="proposed"),
            ])
            summary = searcher.inject_summary(active_only=False)
            assert "Proposed pattern" in summary

    def test_inject_include_global_merges_project_and_global(self):
        """include_global=True should merge project and global facts."""
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            store.save([
                AtomicFact(type=FactType.PREFERENCE, content="Global CLI preference", confidence=1.0, scope="global"),
                AtomicFact(type=FactType.DECISION, content="Blog uses PostgreSQL", confidence=1.0, scope="project", project="blog"),
                AtomicFact(type=FactType.ENVIRONMENT, content="NAS port 443 blocked", confidence=1.0, scope="project", project="nas"),
            ])
            # Without include_global
            summary = searcher.inject_summary(scope="project", project="blog")
            assert "Blog uses PostgreSQL" in summary
            assert "Global CLI preference" not in summary
            assert "NAS port 443" not in summary

            # With include_global
            summary2 = searcher.inject_summary(scope="project", project="blog", include_global=True)
            assert "Blog uses PostgreSQL" in summary2
            assert "Global CLI preference" in summary2
            assert "NAS port 443" not in summary2  # other project excluded

    def test_accept_reject_proposed(self):
        """Accept and reject should work with the store directly."""
        with tempfile.TemporaryDirectory() as tmp:
            config = MemoryConfig(data_dir=tmp)
            store = MemoryStore(config)

            # Save a proposed fact
            fact = AtomicFact(type=FactType.CONVENTION, content="Test pattern", confidence=0.6, status="proposed")
            store.save([fact])

            # Accept
            assert store.load_by_id(fact.id) is not None
            store.edit(fact.id, status="active", confidence=0.9)
            updated = store.load_by_id(fact.id)
            assert updated is not None
            assert updated.status == "active"
            assert updated.confidence == 0.9

            # Reject
            fact2 = AtomicFact(type=FactType.CONVENTION, content="Another pattern", confidence=0.6, status="proposed")
            store.save([fact2])
            store.edit(fact2.id, status="wrong", confidence=0.0)
            rejected = store.load_by_id(fact2.id)
            assert rejected is not None
            assert rejected.status == "wrong"

    def test_inject_summary_supersedes_and_status_filtering(self):
        """Regression: inject should exclude both superseded-IDs and non-active-status facts."""
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            old = AtomicFact(type=FactType.PREFERENCE, content="Old preference", confidence=1.0)
            new = AtomicFact(type=FactType.PREFERENCE, content="New preference", confidence=1.0, supersedes=old.id)
            store.save([old, new])

            summary = searcher.inject_summary(active_only=True)
            assert "New preference" in summary
            assert "Old preference" not in summary  # superseded via supersedes

    def test_inject_emoji_by_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            summary = searcher.inject_summary()
            assert "💡" in summary  # preference
            assert "🔧" in summary  # environment
            assert "✅" in summary  # decision
            assert "❌" in summary  # rejection_reason

    def test_inject_with_date_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            # Save facts to different date files so date filtering works
            store.save([
                AtomicFact(type=FactType.PREFERENCE, content="User prefers CLI", confidence=1.0),
            ], date_str="2026-06-01")
            store.save([
                AtomicFact(type=FactType.LESSON, content="patch tool double-escapes JSON — use write_file instead", confidence=1.0),
            ], date_str="2026-06-03")
            # Only facts from 2026-06-03 onwards
            summary = searcher.inject_summary(date_from="2026-06-03")
            assert "double-escapes" in summary
            assert "CLI" not in summary


class TestTokenizer:
    """Tests for _BM25._tokenize CJK support."""

    def test_latin_only(self):
        tokens = _BM25._tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_cjk_individual_chars(self):
        tokens = _BM25._tokenize("项目")
        # Individual chars
        assert "项" in tokens
        assert "目" in tokens

    def test_cjk_bigrams(self):
        tokens = _BM25._tokenize("项目隔离")
        # Bigrams from consecutive CJK chars
        assert "项目" in tokens
        assert "目隔" in tokens
        assert "隔离" in tokens

    def test_mixed_latin_cjk(self):
        tokens = _BM25._tokenize("用 PostgreSQL 做项目")
        assert "postgresql" in tokens
        assert "项目" in tokens
        assert "做项" in tokens  # CJK bigram crossing "做" + "项"

    def test_cjk_with_punctuation(self):
        tokens = _BM25._tokenize("测试, hello, 世界")
        assert "测试" in tokens  # bigram within CJK run before comma
        assert "世界" in tokens  # bigram within CJK run after comma
        assert "试世" not in tokens  # comma breaks CJK continuity
        assert "hello" in tokens

    def test_empty_string(self):
        assert _BM25._tokenize("") == []

    def test_cjk_only_bigrams(self):
        """A 4-char CJK string should produce 4 unigrams + 3 bigrams."""
        tokens = _BM25._tokenize("一二三四")
        assert len(tokens) == 7  # 4 unigrams + 3 bigrams
        assert tokens.count("一") == 1
        assert tokens.count("一二") == 1
        assert tokens.count("二三") == 1
        assert tokens.count("三四") == 1


class TestSearchEmptyOnNoMatch:
    """When query is provided and BM25 finds nothing, search() should return empty."""

    def test_search_empty_when_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            # Query that definitely won't match any fact
            results = searcher.search(query="xyznonexistent12345")
            assert results == []

    def test_search_still_finds_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            searcher, store = _make_search(tmp)
            _seed_data(store)
            results = searcher.search(query="PostgreSQL")
            assert len(results) >= 1
            assert "PostgreSQL" in results[0].content
