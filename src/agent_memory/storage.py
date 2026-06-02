"""
JSONL-based persistent storage for atomic facts.

Each day's facts live in a separate file. Dedup uses a content-hash
index to avoid O(n) scans. Written in pure Python — zero dependencies.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .core import AtomicFact, MemoryConfig


class MemoryStore:
    """Persistent storage for atomic facts using daily JSONL files.

    Facts are stored in::

        {data_dir}/atoms/{YYYY-MM-DD}.jsonl

    Each line is a JSON object representing one AtomicFact.
    Dedup is O(1) via an in-memory content-hash index.
    """

    def __init__(self, config: MemoryConfig):
        self.config = config
        self._atoms_dir = Path(os.path.expanduser(config.data_dir)) / "atoms"
        self._atoms_dir.mkdir(parents=True, exist_ok=True)
        self._dedup_index: set[str] = set()
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """Scan existing files to rebuild the dedup hash index."""
        self._dedup_index.clear()
        for path in sorted(self._atoms_dir.glob("*.jsonl")):
            for line in path.read_text().splitlines():
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        self._dedup_index.add(data.get("id", ""))
                    except json.JSONDecodeError:
                        continue

    def save(self, facts: list[AtomicFact], date_str: str = "") -> int:
        """Save facts, skipping duplicates. Returns count of new facts saved.

        Args:
            facts: List of AtomicFacts to persist.
            date_str: ISO date string. Defaults to today.

        Returns:
            Number of new (non-duplicate) facts saved.
        """
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        path = self._atoms_dir / f"{date_str}.jsonl"
        new_facts = [f for f in facts if f.id not in self._dedup_index]

        if not new_facts:
            return 0

        # Append to daily file
        with open(path, "a") as f:
            for fact in new_facts:
                fact.source_date = date_str
                f.write(json.dumps(fact.to_dict(), ensure_ascii=False) + "\n")
                self._dedup_index.add(fact.id)

        return len(new_facts)

    def load(
        self,
        date_from: str = "",
        date_to: str = "",
        fact_type: str = "",
    ) -> list[AtomicFact]:
        """Load facts, optionally filtered by date range and type.

        Args:
            date_from: Earliest date (YYYY-MM-DD), inclusive.
            date_to: Latest date (YYYY-MM-DD), inclusive.
            fact_type: Filter by fact type string.

        Returns:
            List of matching AtomicFacts, newest first.
        """
        facts: list[AtomicFact] = []
        for path in sorted(self._atoms_dir.glob("*.jsonl"), reverse=True):
            file_date = path.stem  # YYYY-MM-DD from filename
            if date_from and file_date < date_from:
                break
            if date_to and file_date > date_to:
                continue

            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    fact = AtomicFact.from_dict(json.loads(line))
                    if fact_type and fact.type.value != fact_type:
                        continue
                    facts.append(fact)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

        return facts

    def stats(self) -> dict:
        """Get storage statistics.

        Returns:
            Dict with total count, per-type counts, and storage size.
        """
        total = 0
        by_type: dict[str, int] = {}
        total_bytes = 0

        for path in sorted(self._atoms_dir.glob("*.jsonl")):
            total_bytes += path.stat().st_size
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    data = json.loads(line)
                    t = data.get("type", "unknown")
                    by_type[t] = by_type.get(t, 0) + 1
                except json.JSONDecodeError:
                    continue

        return {
            "total_facts": total,
            "by_type": by_type,
            "storage_bytes": total_bytes,
            "data_dir": str(self._atoms_dir),
        }
