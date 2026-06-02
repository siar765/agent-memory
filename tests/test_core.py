"""Tests for agent_memory.core — AtomicFact, FactType, and MemoryConfig."""

from datetime import datetime, timezone

from agent_memory.core import AtomicFact, FactType, MemoryConfig


class TestFactType:
    def test_values(self):
        assert FactType.PREFERENCE.value == "preference"
        assert FactType.ENVIRONMENT.value == "environment"
        assert FactType.DECISION.value == "decision"
        assert FactType.REJECTION.value == "rejection_reason"
        assert FactType.CONVENTION.value == "convention"
        assert FactType.LESSON.value == "lesson"

    def test_from_string(self):
        assert FactType("preference") == FactType.PREFERENCE
        assert FactType("environment") == FactType.ENVIRONMENT

    def test_invalid_string_raises(self):
        import pytest
        with pytest.raises(ValueError):
            FactType("not_a_valid_type")


class TestAtomicFact:
    def test_minimal_creation(self):
        fact = AtomicFact(type=FactType.PREFERENCE, content="User likes dark mode")
        assert fact.type == FactType.PREFERENCE
        assert fact.content == "User likes dark mode"
        assert 0.8 <= fact.confidence <= 1.0
        assert fact.id != ""
        assert fact.created_at > 0
        assert fact.scope == "global"
        assert fact.project == ""
        assert fact.status == "active"

    def test_id_is_deterministic(self):
        f1 = AtomicFact(type=FactType.PREFERENCE, content="User prefers CLI")
        f2 = AtomicFact(type=FactType.PREFERENCE, content="User prefers CLI")
        assert f1.id == f2.id

    def test_id_different_for_different_content(self):
        f1 = AtomicFact(type=FactType.PREFERENCE, content="User prefers CLI")
        f2 = AtomicFact(type=FactType.PREFERENCE, content="User prefers GUI")
        assert f1.id != f2.id

    def test_id_case_insensitive(self):
        f1 = AtomicFact(type=FactType.PREFERENCE, content="User prefers CLI")
        f2 = AtomicFact(type=FactType.PREFERENCE, content="user prefers cli")
        assert f1.id == f2.id

    def test_id_different_with_different_scope(self):
        """Same content, different scope = different ID."""
        f1 = AtomicFact(type=FactType.PREFERENCE, content="Use PostgreSQL", scope="global")
        f2 = AtomicFact(type=FactType.PREFERENCE, content="Use PostgreSQL", scope="project", project="blog")
        assert f1.id != f2.id

    def test_confidence_clamped(self):
        fact = AtomicFact(type=FactType.DECISION, content="Chose X", confidence=1.5)
        assert fact.confidence == 1.0

    def test_confidence_floor_clamped(self):
        fact = AtomicFact(type=FactType.DECISION, content="Chose X", confidence=-0.5)
        assert fact.confidence == 0.0

    def test_type_from_string_in_post_init(self):
        fact = AtomicFact(type="preference", content="Test")
        assert fact.type == FactType.PREFERENCE

    def test_to_dict_includes_scope_project_status(self):
        fact = AtomicFact(
            type=FactType.LESSON,
            content="Always test before deploy",
            confidence=0.95,
            evidence="User said: 'always test'",
            source_date="2026-06-01",
            scope="project",
            project="agent-memory",
        )
        d = fact.to_dict()
        assert d["type"] == "lesson"
        assert d["content"] == "Always test before deploy"
        assert d["confidence"] == 0.95
        assert d["evidence"] == "User said: 'always test'"
        assert d["source_date"] == "2026-06-01"
        assert d["scope"] == "project"
        assert d["project"] == "agent-memory"
        assert d["status"] == "active"
        assert d["id"] == fact.id
        assert d["created_at"] == fact.created_at

    def test_from_dict_roundtrip(self):
        original = AtomicFact(
            type=FactType.ENVIRONMENT,
            content="Docker port 443 is blocked",
            confidence=1.0,
            evidence="User mentioned network restriction",
            source_date="2026-06-01",
            scope="project",
            project="nas",
        )
        d = original.to_dict()
        restored = AtomicFact.from_dict(d)
        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.content == original.content
        assert restored.confidence == original.confidence
        assert restored.evidence == original.evidence
        assert restored.scope == original.scope
        assert restored.project == original.project
        assert restored.status == original.status

    def test_from_dict_handles_legacy_data(self):
        """Legacy facts without scope/project/status should get defaults."""
        d = {
            "id": "pr:abc123",
            "type": "preference",
            "content": "Legacy fact",
            "confidence": 1.0,
            "evidence": "",
            "source_date": "2026-01-01",
            "supersedes": "",
            "created_at": 1000.0,
        }
        fact = AtomicFact.from_dict(d)
        assert fact.scope == "global"
        assert fact.project == ""
        assert fact.status == "active"

    def test_supersedes_chain(self):
        old = AtomicFact(type=FactType.PREFERENCE, content="User prefers Vim")
        new = AtomicFact(
            type=FactType.PREFERENCE,
            content="User prefers VS Code now",
            supersedes=old.id,
        )
        assert new.supersedes == old.id
        assert new.id != old.id

    def test_repr(self):
        fact = AtomicFact(type=FactType.PREFERENCE, content="User prefers CLI over GUI")
        r = repr(fact)
        assert "preference" in r
        assert "global" in r


class TestMemoryConfig:
    def test_default_values(self):
        config = MemoryConfig()
        assert config.data_dir == "~/.agent/memory"
        assert config.inject_threshold == 0.8
        assert config.max_fact_length == 200
        assert config.default_scope == "global"

    def test_custom_values(self):
        config = MemoryConfig(
            data_dir="/tmp/test-memory",
            inject_threshold=0.9,
            max_fact_length=100,
        )
        assert config.data_dir == "/tmp/test-memory"
        assert config.inject_threshold == 0.9
        assert config.max_fact_length == 100
