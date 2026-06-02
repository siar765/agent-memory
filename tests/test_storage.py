"""Tests for agent_memory.storage — MemoryStore persistence and dedup."""

import json
import os
import tempfile
from pathlib import Path

from agent_memory.core import AtomicFact, FactType, MemoryConfig
from agent_memory.storage import MemoryStore, _redact_secrets


def _make_store(tmp_dir: str) -> MemoryStore:
    config = MemoryConfig(data_dir=tmp_dir)
    return MemoryStore(config)


def _fact(content: str, type_: FactType = FactType.PREFERENCE, confidence: float = 1.0) -> AtomicFact:
    return AtomicFact(type=type_, content=content, confidence=confidence)


class TestMemoryStore:
    def test_create_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            atoms_dir = Path(tmp) / "atoms"
            assert not atoms_dir.exists()
            _make_store(tmp)
            assert atoms_dir.exists()

    def test_save_creates_jsonl_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            saved = store.save([_fact("User likes dark mode")])
            assert saved == 1

            # Check file exists and has content
            files = list(Path(tmp).glob("atoms/*.jsonl"))
            assert len(files) == 1
            lines = files[0].read_text().splitlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["content"] == "User likes dark mode"

    def test_save_returns_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            count = store.save([
                _fact("Fact A"),
                _fact("Fact B"),
                _fact("Fact C"),
            ])
            assert count == 3

    def test_dedup_same_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            f = _fact("Unique content")
            assert store.save([f]) == 1
            assert store.save([f]) == 0

    def test_dedup_identical_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            assert store.save([_fact("Same content")]) == 1
            assert store.save([_fact("Same content")]) == 0

    def test_dedup_persists_across_store_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store1 = _make_store(tmp)
            store1.save([_fact("Persistent dedup")])

            store2 = _make_store(tmp)
            assert store2.save([_fact("Persistent dedup")]) == 0

    def test_date_str_parameter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.save([_fact("Fact A")], date_str="2026-01-01")
            store.save([_fact("Fact B")], date_str="2026-01-02")

            files = sorted(Path(tmp).glob("atoms/*.jsonl"))
            assert len(files) == 2
            assert files[0].stem == "2026-01-01"
            assert files[1].stem == "2026-01-02"

    def test_load_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.save([_fact("Fact A")], date_str="2026-01-01")
            store.save([_fact("Fact B")], date_str="2026-01-02")

            all_facts = store.load()
            assert len(all_facts) == 2

    def test_load_with_date_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.save([_fact("Fact A")], date_str="2026-01-01")
            store.save([_fact("Fact B")], date_str="2026-01-02")
            store.save([_fact("Fact C")], date_str="2026-01-03")

            filtered = store.load(date_from="2026-01-02")
            assert len(filtered) == 2
            # It loads newest first, but both should be from 01-02 or later
            dates = {f.source_date for f in filtered}
            assert "2026-01-01" not in dates

    def test_load_with_type_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.save([_fact("Pref", FactType.PREFERENCE)], date_str="2026-01-01")
            store.save([_fact("Env", FactType.ENVIRONMENT)], date_str="2026-01-02")

            prefs = store.load(fact_type="preference")
            assert len(prefs) == 1
            assert prefs[0].type == FactType.PREFERENCE

    def test_load_with_scope_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.save([
                AtomicFact(type=FactType.PREFERENCE, content="Global fact", scope="global"),
                AtomicFact(type=FactType.DECISION, content="Project fact", scope="project", project="blog"),
            ])

            global_facts = store.load(scope="global")
            assert len(global_facts) == 1
            assert global_facts[0].content == "Global fact"

            project_facts = store.load(scope="project", project="blog")
            assert len(project_facts) == 1
            assert project_facts[0].content == "Project fact"

    def test_load_with_status_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.save([
                AtomicFact(type=FactType.PREFERENCE, content="Active fact", status="active"),
                AtomicFact(type=FactType.PREFERENCE, content="Archived fact", status="archived"),
            ])

            active = store.load(status="active")
            assert len(active) == 1
            assert active[0].content == "Active fact"

            archived = store.load(status="archived")
            assert len(archived) == 1

    def test_load_active_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.save([
                AtomicFact(type=FactType.PREFERENCE, content="Active fact"),
                AtomicFact(type=FactType.PREFERENCE, content="Bad fact", status="wrong"),
            ])

            active = store.load(active_only=True)
            assert len(active) == 1
            assert active[0].content == "Active fact"

    def test_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.save([
                _fact("Pref A", FactType.PREFERENCE),
                _fact("Pref B", FactType.PREFERENCE),
                _fact("Env A", FactType.ENVIRONMENT),
            ])

            s = store.stats()
            assert s["total_facts"] == 3
            assert s["by_type"]["preference"] == 2
            assert s["by_type"]["environment"] == 1
            assert s["storage_bytes"] > 0
            assert "by_status" in s
            assert "by_scope" in s

    def test_corrupted_line_skipped_during_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Manually write a corrupted JSONL file
            atoms_dir = Path(tmp) / "atoms"
            atoms_dir.mkdir(parents=True)
            bad_file = atoms_dir / "2026-01-01.jsonl"
            bad_file.write_text('{"type": "preference", "content": "Good fact"}\nnot json\n{"type": "environment", "content": "Good too"}\n')

            store = _make_store(tmp)
            facts = store.load()
            assert len(facts) == 2  # corrupted line skipped

    def test_save_with_lock_works(self):
        """Regression: file locking should not break normal saves."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            for i in range(10):
                store.save([_fact(f"Fact {i}")])
            assert store.stats()["total_facts"] == 10

    def test_edit_recalculates_id_on_content_change(self):
        """Editing content should recalculate the fact's ID."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            fact = _fact("Old content")
            store.save([fact])
            old_id = fact.id

            # Edit content
            store.edit(old_id, content="New content")

            # Old ID should no longer exist
            assert store.load_by_id(old_id) is None

            # New ID should exist
            updated = AtomicFact(type=FactType.PREFERENCE, content="New content")
            assert store.load_by_id(updated.id) is not None

    def test_save_redacts_secrets(self):
        """Secrets in content/evidence should be redacted before save."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            fact = AtomicFact(
                type=FactType.ENVIRONMENT,
                content="API key is sk-abc123def456ghijklmnopqrstuvwxyz",
            )
            store.save([fact])

            loaded = store.load()
            assert len(loaded) == 1
            assert "[REDACTED]" in loaded[0].content
            assert "sk-abc123" not in loaded[0].content


class TestRedactSecrets:
    def test_api_key_pattern(self):
        assert "[REDACTED]" in _redact_secrets("sk-abc123DEF456ghijklmnopqrstuvwx")

    def test_github_token(self):
        assert "[REDACTED]" in _redact_secrets("ghp_abc123DEF456ghijklmnopqrstuvwx")

    def test_credential_pair(self):
        result = _redact_secrets('password = "super-secret-123"')
        assert "[REDACTED]" in result

    def test_private_key(self):
        result = _redact_secrets("-----BEGIN RSA PRIVATE KEY-----\nABCDEF")
        assert "[REDACTED]" in result
