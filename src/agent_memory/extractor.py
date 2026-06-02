"""
LLM-powered fact extraction — turns conversation traces into structured AtomicFacts.

Uses any OpenAI-compatible API. The extraction prompt is engineered for
precision over recall: better to miss a fact than to fabricate one.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

from .core import AtomicFact, FactType, MemoryConfig

# System prompt for fact extraction — optimized for precision
EXTRACT_PROMPT = """You are a memory extraction assistant. Your job is to extract atomic facts from agent-user conversations.

Each atomic fact must be:
1. **Atomic** — one fact per entry. If a statement contains multiple facts, split them.
2. **Typed** — one of: preference, environment, decision, rejection_reason, convention, lesson
3. **Confidence-scored** — 1.0 if explicitly stated, 0.9 if strongly implied, 0.8 if inferred
4. **Evidenced** — quote the exact text that supports this fact
5. **Eternal** — only extract facts that will still be true tomorrow. Skip transient states.

Type definitions:
- **preference**: User likes/dislikes, habits, preferred tools or approaches
- **environment**: System constraints, network limitations, hardware specs, tool availability
- **decision**: Explicit choices made, paths selected
- **rejection_reason**: Why a particular option was ruled out
- **convention**: Recurring patterns, naming conventions, workflow habits
- **lesson**: Mistakes, corrections, things learned the hard way

Output format: JSON array only, no markdown, no explanation.
```json
[
  {
    "type": "preference",
    "content": "User prefers CLI over GUI for system management",
    "confidence": 1.0,
    "evidence": "User: 'I prefer CLI over GUI'"
  }
]
```

Rules:
- Extract facts even from single exchanges
- If the same fact appears multiple times with different details, merge into one entry
- If the user corrects a previous statement, mark it as separate fact (evolution will be tracked externally)
- Return [] if nothing worth remembering
- Confidence < 0.7 means DON'T extract — be conservative"""


class FactExtractor:
    """Extracts AtomicFacts from conversation text using an LLM."""

    def __init__(self, config: MemoryConfig):
        self.config = config

    def extract(self, conversation_text: str) -> list[AtomicFact]:
        """Extract atomic facts from conversation text.

        Args:
            conversation_text: Raw conversation text to analyze.

        Returns:
            List of extracted AtomicFacts. Empty if extraction fails.
        """
        if not conversation_text.strip():
            return []

        # Truncate to prevent token overflow
        text = conversation_text[:25_000]

        payload = json.dumps({
            "model": self.config.llm_model,
            "messages": [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": f"Extract atomic facts from:\\n\\n{text}"},
            ],
            "max_tokens": 4096,
            "temperature": 0.2,
        }).encode("utf-8")

        try:
            result = self._call_llm(payload)
            atoms = self._parse_response(result)
            return atoms
        except Exception as e:
            print(f"[agent-memory] LLM extraction failed: {e}", file=sys.stderr)
            return []

    def _call_llm(self, payload: bytes) -> str:
        """Call the LLM API with retry logic."""
        last_error = None

        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    self.config.llm_endpoint,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.config.llm_api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.config.extract_timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")
            except (urllib.error.HTTPError, urllib.error.URLError) as e:
                last_error = e
                if attempt < 2:
                    time.sleep(2 ** attempt)  # exponential backoff
                    continue
                raise

        raise last_error  # type: ignore

    def _parse_response(self, content: str) -> list[AtomicFact]:
        """Parse LLM response into AtomicFacts with robust JSON extraction."""
        if not content:
            return []

        # Try to extract JSON from markdown code blocks first
        json_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL
        )
        json_str = json_match.group(1) if json_match else content

        # Find the first JSON array
        array_match = re.search(r"\[.*\]", json_str, re.DOTALL)
        if not array_match:
            return []

        try:
            data = json.loads(array_match.group(0))
        except json.JSONDecodeError:
            return []

        if not isinstance(data, list):
            return []

        atoms = []
        for item in data:
            if not isinstance(item, dict) or "content" not in item:
                continue
            try:
                fact_type = FactType(item.get("type", "convention"))
            except ValueError:
                continue

            atoms.append(AtomicFact(
                type=fact_type,
                content=str(item["content"])[:self.config.max_fact_length],
                confidence=min(float(item.get("confidence", 0.8)), 1.0),
                evidence=str(item.get("evidence", "")),
            ))

        return atoms
