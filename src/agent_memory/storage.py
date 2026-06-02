"""
JSONL-based persistent storage for atomic facts.

Each day's facts live in a separate file. Dedup uses a content-hash
index to avoid O(n) scans. Written in pure Python — zero dependencies.

Supports CRUD operations: save, load, delete, edit, forget, validate.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .core import AtomicFact, FactStatus, FactType, MemoryConfig

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


# Secret patterns for pre-save redaction
SECRET_PATTERNS = [
    re.compile(r"\b(?:sk-|pk-|ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_\-]{20,}\b"),  # API keys
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access keys
    re.compile(r"(?i)(?:password|passwd|secret|token|private[_-]?key)\s*[:=]\s*\S{8,}"),  # creds
    re.compile(r"-----BEGIN\s+(?:RSA\s+PRIVATE|EC\s+PRIVATE|DSA\s+PRIVATE|OPENSSH\s+PRIVATE|PRIVATE)\s+KEY-----"),  # private keys
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),  # likely tokens/hashes (32+ hex chars)
]


def _redact_secrets(text: str) -> str:
    """Replace sensitive patterns with [REDACTED]."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _atomic_write(path: Path, content: str) -> None:
    """Write to a temp file first, then atomically replace.

    Prevents partial writes from corrupting the file on crash.
    """
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as tmp:
            _lock_file(tmp)
            try:
                tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
            finally:
                _unlock_file(tmp)
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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

    def save(self, facts: list[AtomicFact], date_str: str = "",
             scope: str = "", project: str = "") -> int:
        """Save facts, skipping duplicates. Returns count of new facts saved.

        Automatically redacts secret patterns from content and evidence
        before persisting.

        Args:
            facts: List of AtomicFacts to persist.
            date_str: ISO date string. Defaults to today.
            scope: Filter: only save facts matching this scope.
            project: Filter: only save facts matching this project.

        Returns:
            Number of new (non-duplicate) facts saved.
        """
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Apply scope/project filter if specified
        if scope:
            facts = [f for f in facts if f.scope == scope]
        if project:
            facts = [f for f in facts if f.project == project]

        path = self._atoms_dir / f"{date_str}.jsonl"
        new_facts = [f for f in facts if f.id not in self._dedup_index]

        if not new_facts:
            return 0

        # Pre-save secret redaction
        lines = []
        for fact in new_facts:
            fact.source_date = date_str
            content_clean = _redact_secrets(fact.content)
            evidence_clean = _redact_secrets(fact.evidence)
            if content_clean != fact.content:
                fact.content = content_clean
            if evidence_clean != fact.evidence:
                fact.evidence = evidence_clean
            lines.append(json.dumps(fact.to_dict(), ensure_ascii=False))

        # Append to daily file with lock
        if path.exists():
            existing = path.read_text()
            content = existing + ("\n" if existing and not existing.endswith("\n") else "") + "\n".join(lines) + "\n"
        else:
            content = "\n".join(lines) + "\n"

        _atomic_write(path, content)

        for fact in new_facts:
            self._dedup_index.add(fact.id)

        return len(new_facts)

    def load(
        self,
        date_from: str = "",
        date_to: str = "",
        fact_type: str = "",
        scope: str = "",
        project: str = "",
        status: str = "",
        active_only: bool = False,
    ) -> list[AtomicFact]:
        """Load facts with optional filters.

        Args:
            date_from: Earliest date (YYYY-MM-DD), inclusive.
            date_to: Latest date (YYYY-MM-DD), inclusive.
            fact_type: Filter by fact type string.
            scope: Filter by scope (``global`` / ``project``).
            project: Filter by project name.
            status: Filter by status string.
            active_only: Shortcut for ``status="active"``.

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
                    if scope and fact.scope != scope:
                        continue
                    if project and fact.project != project:
                        continue
                    if active_only or status == "active":
                        if fact.status != "active":
                            continue
                    elif status and fact.status != status:
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

        Removes the matching line from the JSONL file via atomic rewrite.

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
                content = "\n".join(new_lines)
                if new_lines:
                    content += "\n"
                _atomic_write(path, content)
                self._rebuild_index()
                return True

        return False

    def edit(self, fact_id: str, **updates) -> bool:
        """Edit fields of an existing fact.

        If content or type changes, the ID is automatically recalculated
        and the old ID is recorded in ``supersedes``.

        Args:
            fact_id: The fact's unique ID to edit.
            **updates: Fields to update (content, confidence, type, evidence,
                       supersedes, status, scope, project).

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
                        content_changed = "content" in updates
                        type_changed = "type" in updates

                        # Apply updates
                        for key, value in updates.items():
                            if key in ("type", "content", "evidence", "supersedes",
                                       "source_date", "status", "scope", "project"):
                                data[key] = value
                            elif key == "confidence":
                                data[key] = max(0.0, min(float(value), 1.0))

                        # Recalculate ID if content or type changed
                        if content_changed or type_changed:
                            # Create a temporary fact to get the new ID
                            tmp = AtomicFact(
                                type=FactType(data["type"]),
                                content=data["content"],
                                scope=data.get("scope", "global"),
                                project=data.get("project", ""),
                            )
                            new_id = tmp.id
                            if new_id != fact_id:
                                data["supersedes"] = fact_id
                                data["id"] = new_id

                        new_lines.append(json.dumps(data, ensure_ascii=False))
                    else:
                        new_lines.append(line)
                except json.JSONDecodeError:
                    new_lines.append(line)

            if found:
                content = "\n".join(new_lines)
                if new_lines:
                    content += "\n"
                _atomic_write(path, content)
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
                content = "\n".join(new_lines)
                if new_lines:
                    content += "\n"
                _atomic_write(path, content)

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
        - Status values are valid
        - Scope/project consistency

        Returns:
            List of issues found (empty = clean).
        """
        issues = []
        all_ids: set[str] = set()
        supersedes_refs: set[str] = set()
        valid_statuses = {"active", "archived", "wrong", "superseded"}
        valid_scopes = {"global", "project"}

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

                # Validate status
                status = data.get("status", "active")
                if status not in valid_statuses:
                    issues.append({
                        "file": str(path),
                        "line": line_num,
                        "type": "invalid_status",
                        "detail": f"Unknown status: {status}",
                    })

                # Validate scope
                scope = data.get("scope", "global")
                if scope not in valid_scopes:
                    issues.append({
                        "file": str(path),
                        "line": line_num,
                        "type": "invalid_scope",
                        "detail": f"Unknown scope: {scope}",
                    })

                # Project requires scope="project"
                project = data.get("project", "")
                if project and scope != "project":
                    issues.append({
                        "file": str(path),
                        "line": line_num,
                        "type": "scope_project_mismatch",
                        "detail": f"project='{project}' but scope='{scope}'",
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
            Dict with total count, per-type counts, status counts,
            scope/project breakdown, and storage size.
        """
        total = 0
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_scope: dict[str, int] = {}
        by_project: dict[str, int] = {}
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

                    s = data.get("status", "active")
                    by_status[s] = by_status.get(s, 0) + 1

                    sc = data.get("scope", "global")
                    by_scope[sc] = by_scope.get(sc, 0) + 1

                    p = data.get("project", "") or "(none)"
                    by_project[p] = by_project.get(p, 0) + 1

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
            "by_status": by_status,
            "by_scope": by_scope,
            "by_project": by_project,
            "storage_bytes": total_bytes,
            "data_dir": str(self._atoms_dir),
        }
