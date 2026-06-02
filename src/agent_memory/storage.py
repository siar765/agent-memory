"""
JSONL-based persistent storage for atomic facts.

Each day's facts live in a separate file. Dedup uses a content-hash
index to avoid O(n) scans. Written in pure Python — zero dependencies.

Supports CRUD operations: save, load, delete, edit, forget, validate.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .core import AtomicFact, MemoryConfig

# File locking for concurrent write safety — optional, no external deps
try:
    import fcntl

    def _lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

except ImportError:
    # Fallback: no locking (Windows or restricted environments)
    def _lock_file(f):
        pass

    def _unlock_file(f):
        pass


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

        # Append to daily file with lock
        with open(path, "a") as f:
            _lock_file(f)
            try:
                for fact in new_facts:
                    fact.source_date = date_str
                    f.write(json.dumps(fact.to_dict(), ensure_ascii=False) + "\n")
                    self._dedup_index.add(fact.id)
            finally:
                _unlock_file(f)

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

    def load_by_id(self, fact_id: str) -> AtomicFact | None:
        """Load a single fact by its ID.

        Args:
            fact_id: The fact's unique ID.

        Returns:
            The AtomicFact if found, None otherwise.
        """
        for path in sorted(self._atoms_dir.glob("*.jsonl"), reverse=True):
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("id") == fact_id:
                        return AtomicFact.from_dict(data)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        return None

    def delete(self, fact_id: str) -> bool:
        """Delete a single fact by its ID.

        Removes the matching line from the JSONL file and compact storage.

        Args:
            fact_id: The fact's unique ID to delete.

        Returns:
            True if found and deleted, False if not found.
        """
        found = False
        for path in sorted(self._atoms_dir.glob("*.jsonl"), reverse=True):
            lines = path.read_text().splitlines()
            new_lines = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("id") == fact_id:
                        found = True
                        continue  # skip this line
                    new_lines.append(line)
                except json.JSONDecodeError:
                    new_lines.append(line)

            if found:
                with open(path, "w") as f:
                    _lock_file(f)
                    try:
                        f.write("\n".join(new_lines))
                        if new_lines:
                            f.write("\n")  # trailing newline
                    finally:
                        _unlock_file(f)
                self._rebuild_index()
                return True

        return False

    def edit(self, fact_id: str, **updates) -> bool:
        """Edit fields of an existing fact.

        Args:
            fact_id: The fact's unique ID to edit.
            **updates: Fields to update (content, confidence, type, evidence, supersedes).

        Returns:
            True if found and edited, False if not found.
        """
        found = False
        for path in sorted(self._atoms_dir.glob("*.jsonl"), reverse=True):
            lines = path.read_text().splitlines()
            new_lines = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("id") == fact_id:
                        found = True
                        # Apply updates
                        for key, value in updates.items():
                            if key in ("type", "content", "evidence", "supersedes", "source_date"):
                                data[key] = value
                            elif key == "confidence":
                                data[key] = max(0.0, min(float(value), 1.0))
                        # Re-serialize
                        new_lines.append(json.dumps(data, ensure_ascii=False))
                    else:
                        new_lines.append(line)
                except json.JSONDecodeError:
                    new_lines.append(line)

            if found:
                with open(path, "w") as f:
                    _lock_file(f)
                    try:
                        f.write("\n".join(new_lines))
                        if new_lines:
                            f.write("\n")
                    finally:
                        _unlock_file(f)
                self._rebuild_index()
                return True

        return False

    def forget(self, query: str) -> int:
        """Delete all facts matching a keyword query.

        Args:
            query: Keyword to search in fact content (case-insensitive).

        Returns:
            Number of facts deleted.
        """
        query_lower = query.lower()
        deleted = 0

        for path in sorted(self._atoms_dir.glob("*.jsonl"), reverse=True):
            lines = path.read_text().splitlines()
            new_lines = []
            changed = False
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    content = (data.get("content", "") + " " + data.get("evidence", "")).lower()
                    if query_lower in content:
                        deleted += 1
                        changed = True
                        continue
                    new_lines.append(line)
                except json.JSONDecodeError:
                    new_lines.append(line)

            if changed:
                with open(path, "w") as f:
                    _lock_file(f)
                    try:
                        f.write("\n".join(new_lines))
                        if new_lines:
                            f.write("\n")
                    finally:
                        _unlock_file(f)

        if deleted > 0:
            self._rebuild_index()

        return deleted

    def validate(self) -> list[dict]:
        """Validate storage integrity.

        Checks:
        - All lines are valid JSON
        - All entries have required fields
        - No duplicate IDs
        - All supersedes references point to existing facts

        Returns:
            List of issues found (empty = clean).
        """
        issues = []
        all_ids: set[str] = set()
        supersedes_refs: set[str] = set()

        for path in sorted(self._atoms_dir.glob("*.jsonl")):
            for line_num, line in enumerate(path.read_text().splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    issues.append({
                        "file": str(path),
                        "line": line_num,
                        "type": "parse_error",
                        "detail": str(e),
                    })
                    continue

                fact_id = data.get("id", "")
                if not fact_id:
                    issues.append({
                        "file": str(path),
                        "line": line_num,
                        "type": "missing_id",
                        "detail": "Fact has no id field",
                    })
                elif fact_id in all_ids:
                    issues.append({
                        "file": str(path),
                        "line": line_num,
                        "type": "duplicate_id",
                        "detail": f"Duplicate id: {fact_id}",
                    })
                else:
                    all_ids.add(fact_id)

                # Check required fields
                for field in ("type", "content", "confidence"):
                    if field not in data:
                        issues.append({
                            "file": str(path),
                            "line": line_num,
                            "type": "missing_field",
                            "detail": f"Missing field: {field}",
                        })

                # Track supersedes references
                ss = data.get("supersedes", "")
                if ss:
                    supersedes_refs.add(ss)

                # Validate type
                if data.get("type") not in ("preference", "environment", "decision",
                                              "rejection_reason", "convention", "lesson"):
                    issues.append({
                        "file": str(path),
                        "line": line_num,
                        "type": "invalid_type",
                        "detail": f"Unknown type: {data.get('type')}",
                    })

        # Check supersedes references
        for ref in supersedes_refs:
            if ref not in all_ids:
                issues.append({
                    "file": "(cross-file)",
                    "line": 0,
                    "type": "dangling_supersedes",
                    "detail": f"supersedes references non-existent id: {ref}",
                })

        return issues

    def stats(self) -> dict:
        """Get storage statistics.

        Returns:
            Dict with total count, per-type counts, and storage size.
        """
        total = 0
        by_type: dict[str, int] = {}
        total_bytes = 0
        active = 0
        superseded = 0

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
                    if data.get("supersedes"):
                        superseded += 1
                    else:
                        active += 1
                except json.JSONDecodeError:
                    continue

        return {
            "total_facts": total,
            "active_facts": active,
            "superseded_facts": superseded,
            "by_type": by_type,
            "storage_bytes": total_bytes,
            "data_dir": str(self._atoms_dir),
        }
