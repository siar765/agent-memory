"""Tests for agent_memory.extractor — FactExtractor and confidence filtering."""

import json

from agent_memory.core import AtomicFact, FactType, MemoryConfig
from agent_memory.extractor import FactExtractor


def _make_config():
    return MemoryConfig(
        data_dir="/tmp/agent-memory-test",
        llm_api_key="test-key",
        llm_endpoint="http://localhost:9999/v1/chat/completions",  # won't be called
    )


class TestParseResponse:
    """Test _parse_response directly — the LLM-calling path is integration-tested."""

    def setup_method(self):
        self.extractor = FactExtractor(_make_config())

    def test_empty_response(self):
        assert self.extractor._parse_response("") == []

    def test_json_array_direct(self):
        content = json.dumps([
            {"type": "preference", "content": "User likes dark mode", "confidence": 1.0},
        ])
        facts = self.extractor._parse_response(content)
        assert len(facts) == 1
        assert facts[0].content == "User likes dark mode"
        assert facts[0].confidence == 1.0

    def test_markdown_code_block(self):
        content = """```json
        [{"type": "environment", "content": "Port 443 blocked", "confidence": 1.0}]
        ```"""
        facts = self.extractor._parse_response(content)
        assert len(facts) == 1
        assert facts[0].type == FactType.ENVIRONMENT

    def test_multiple_facts(self):
        content = json.dumps([
            {"type": "preference", "content": "Prefers CLI", "confidence": 1.0},
            {"type": "environment", "content": "Uses Docker", "confidence": 0.9},
            {"type": "decision", "content": "Chose PostgreSQL", "confidence": 0.95},
        ])
        facts = self.extractor._parse_response(content)
        assert len(facts) == 3

    def test_confidence_below_threshold_discarded(self):
        """Hard confidence gate: < 0.7 gets dropped."""
        content = json.dumps([
            {"type": "preference", "content": "This is certain", "confidence": 1.0},
            {"type": "preference", "content": "This is speculative", "confidence": 0.6},
        ])
        facts = self.extractor._parse_response(content)
        assert len(facts) == 1
        assert facts[0].content == "This is certain"

    def test_confidence_edge_at_threshold(self):
        """At exactly 0.7, should be kept."""
        content = json.dumps([
            {"type": "preference", "content": "Borderline fact", "confidence": 0.7},
        ])
        facts = self.extractor._parse_response(content)
        assert len(facts) == 1

    def test_confidence_clamped_to_1_0(self):
        content = json.dumps([
            {"type": "preference", "content": "Overconfident", "confidence": 1.5},
        ])
        facts = self.extractor._parse_response(content)
        assert len(facts) == 1
        assert facts[0].confidence == 1.0

    def test_missing_confidence_defaults_to_0_8(self):
        content = json.dumps([
            {"type": "preference", "content": "No confidence given"},
        ])
        facts = self.extractor._parse_response(content)
        assert len(facts) == 1
        assert facts[0].confidence == 0.8

    def test_item_without_content_skipped(self):
        content = json.dumps([
            {"type": "preference", "content": "Valid fact", "confidence": 1.0},
            {"type": "environment", "confidence": 0.9},  # missing content
        ])
        facts = self.extractor._parse_response(content)
        assert len(facts) == 1

    def test_invalid_type_falls_back_to_convention(self):
        """If model returns an unknown type, it's rejected."""
        content = json.dumps([
            {"type": "invalid_type", "content": "Some fact", "confidence": 0.9},
        ])
        facts = self.extractor._parse_response(content)
        assert len(facts) == 0

    def test_content_truncated_to_max_length(self):
        config = MemoryConfig(max_fact_length=20)
        extractor = FactExtractor(config)
        content = json.dumps([
            {"type": "preference", "content": "This is a very long fact that should be truncated", "confidence": 1.0},
        ])
        facts = extractor._parse_response(content)
        assert len(facts) == 1
        assert len(facts[0].content) == 20

    def test_non_list_response(self):
        content = '{"type": "preference", "content": "Not a list"}'
        facts = self.extractor._parse_response(content)
        assert len(facts) == 0

    def test_garbage_input(self):
        facts = self.extractor._parse_response("not json at all {{{")
        assert len(facts) == 0

    def test_valid_json_but_not_array(self):
        content = '{"key": "value"}'
        facts = self.extractor._parse_response(content)
        assert len(facts) == 0


class TestExtractMethod:
    """Test FactExtractor.extract() logic — doesn't call real LLM."""

    def test_empty_text_returns_empty(self):
        extractor = FactExtractor(_make_config())
        assert extractor.extract("") == []
        assert extractor.extract("   ") == []
        assert extractor.extract("\n\n\n") == []
