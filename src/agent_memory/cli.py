"""
Command-line interface for agent-memory.

Usage::

    # Extract facts from a conversation file
    echo "..." | agent-memory extract

    # Extract with interactive review
    echo "..." | agent-memory extract --review

    # Search stored facts
    agent-memory search --query "preference" --type preference

    # Generate injection summary
    agent-memory inject --query "docker"

    # Manage facts
    agent-memory list
    agent-memory list --scope project --project agent-memory
    agent-memory show <id>
    agent-memory delete <id>
    agent-memory edit <id> --content "new text"
    agent-memory forget --query "old info"
    agent-memory redact <id>

    # Validate storage integrity
    agent-memory validate

    # View stats
    agent-memory stats

    # Generate user profile from preference facts
    agent-memory summarize
    agent-memory summarize --topic CLI --min-confidence 0.8
    agent-memory summarize --format text --save

    # Trace evolution history
    agent-memory history <id>
    agent-memory history --query "dark mode"

    # Propose a new fact (low confidence, requires review)
    agent-memory propose "User checks crypto prices daily" --type convention

    # Review proposed facts
    agent-memory review
    agent-memory accept pr:xxx --confidence 0.9
    agent-memory reject pr:xxx
    agent-memory reject pr:xxx --delete

    # Inject with project + global preferences merged
    agent-memory inject --scope project --project blog --include-global
"""

from __future__ import annotations

import sys
from pathlib import Path

from .core import AtomicFact, FactType, MemoryConfig
from .extractor import FactExtractor, FactExtractorError, ParseError
from .storage import MemoryStore
from .search import MemorySearch


def _build_config() -> MemoryConfig:
    """Build config from environment variables with sensible defaults."""
    import os

    return MemoryConfig(
        data_dir=os.environ.get("AGENT_MEMORY_DIR", "~/.agent/memory"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_endpoint=os.environ.get(
            "LLM_ENDPOINT",
            os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1/chat/completions"),
        ),
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
    )


def cmd_extract(args: list[str]) -> None:
    """Extract facts from stdin."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--review", action="store_true", help="Interactive review before saving")
    parser.add_argument("--scope", default="global", help="Scope for extracted facts (global|project)")
    parser.add_argument("--project", default="", help="Project name (required if scope=project)")
    opts = parser.parse_args(args)

    text = sys.stdin.read()
    if not text.strip():
        print("[agent-memory] No input on stdin", file=sys.stderr)
        sys.exit(1)

    config = _build_config()

    if not config.llm_api_key:
        print("[agent-memory] ERROR: LLM_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    extractor = FactExtractor(config)
    store = MemoryStore(config)

    try:
        facts = extractor.extract(text)
    except FactExtractorError as e:
        print(f"[agent-memory] ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if not facts:
        print("[agent-memory] No facts extracted (below confidence threshold or empty)")
        return

    # Apply scope/project
    for f in facts:
        f.scope = opts.scope
        f.project = opts.project

    # Interactive review mode
    if opts.review:
        print(f"[agent-memory] Reviewing {len(facts)} extracted facts:\n")
        keep = []
        for i, f in enumerate(facts, 1):
            print(f"  [{i}] [{f.type.value:18s}] {f.confidence:.0%} | {f.content}")
            evidence = f.evidence[:120] + "..." if len(f.evidence) > 120 else f.evidence
            print(f"       Evidence: {evidence}\n")
            while True:
                choice = input(f"       Keep [Y/n/e]dit? ").strip().lower()
                if choice in ("", "y", "yes"):
                    keep.append(f)
                    break
                elif choice in ("n", "no"):
                    print(f"       [Skipped]")
                    break
                elif choice in ("e", "edit"):
                    new_content = input(f"       New content: ").strip()
                    if new_content:
                        f.content = new_content
                        keep.append(f)
                        print(f"       [Edited]")
                    break
                else:
                    print(f"       Enter Y (keep), n (skip), or e (edit)")
        facts = keep
        print(f"\n[agent-memory] Kept {len(facts)} of {len(keep) + (sum(1 for _ in []))} facts" if False else
              f"[agent-memory] Kept {len(facts)} facts after review")
        print()

    if not facts:
        print("[agent-memory] No facts to save after review")
        return

    saved = store.save(facts, scope=opts.scope, project=opts.project)

    # Extraction report
    print(f"[agent-memory] Extracted {len(facts)} facts, saved {saved} new")

    # Confidence distribution
    conf_dist = {"1.0": 0, "0.9": 0, "0.8": 0}
    for f in facts:
        key = f"{f.confidence:.1f}"
        conf_dist[key] = conf_dist.get(key, 0) + 1
    print(f"  Confidence distribution: {conf_dist}")

    # Type distribution
    from collections import Counter
    type_dist = Counter(f.type.value for f in facts)
    print(f"  Type distribution: {dict(type_dist.most_common())}")

    # List facts
    for f in facts:
        print(f"  [{f.scope}/{f.project or '*':10s}] [{f.type.value:18s}] {f.confidence:.0%} | {f.content}")

    if len(facts) > saved:
        print(f"  ({len(facts) - saved} duplicates skipped)")


def cmd_search(args: list[str]) -> None:
    """Search stored facts."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--type", default="")
    parser.add_argument("--scope", default="")
    parser.add_argument("--project", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--all", action="store_true", help="Include non-active facts (wrong, archived, superseded, proposed)")
    parser.add_argument("--no-bm25", action="store_true", help="Disable BM25 ranking")
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)
    searcher = MemorySearch(store)

    facts = searcher.search(
        query=opts.query,
        fact_type=opts.type,
        scope=opts.scope,
        project=opts.project,
        status=opts.status,
        active_only=not opts.all,
        limit=opts.limit,
        min_confidence=opts.min_confidence,
        use_bm25=not opts.no_bm25,
    )

    if not facts:
        print("[agent-memory] No matching facts")
        return

    print(f"[agent-memory] {len(facts)} matching facts:")
    for f in facts:
        label = ""
        if f.status != "active":
            label = f" [{f.status}]"
        print(f"  [{f.scope}/{f.project or '*':10s}] [{f.type.value:18s}] {f.confidence:.0%} | {f.source_date} | {f.content[:120]}{label}")


def cmd_inject(args: list[str]) -> None:
    """Generate injection summary for system prompt."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--min-confidence", type=float, default=0.8)
    parser.add_argument("--date-from", default="")
    parser.add_argument("--scope", default="", help="Filter by scope (global|project)")
    parser.add_argument("--project", default="", help="Filter by project name")
    parser.add_argument("--query", default="", help="Task context for relevance ranking")
    parser.add_argument("--all", action="store_true", help="Include non-active facts too")
    parser.add_argument("--include-global", action="store_true",
                        help="Also include global preferences (auto-enabled when --project is set without --scope)")
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)
    searcher = MemorySearch(store)

    summary = searcher.inject_summary(
        limit=opts.limit,
        min_confidence=opts.min_confidence,
        date_from=opts.date_from,
        query=opts.query,
        active_only=not opts.all,
        scope=opts.scope,
        project=opts.project,
        include_global=opts.include_global,
    )

    if summary:
        print(summary)
    else:
        print("[agent-memory] No facts meet the injection threshold")


def cmd_stats(args: list[str]) -> None:
    """Show storage statistics."""
    config = _build_config()
    store = MemoryStore(config)
    stats = store.stats()

    print(f"Agent Memory Statistics")
    print(f"{'=' * 40}")
    print(f"  Total facts:     {stats['total_facts']}")
    print(f"  Active facts:    {stats['active_facts']}")
    print(f"  Superseded:      {stats['superseded_facts']}")
    print(f"  Storage used:    {stats['storage_bytes']:,} bytes")
    print(f"  Data directory:  {stats['data_dir']}")
    print()

    print(f"  By type:")
    for t, count in sorted(stats["by_type"].items(), key=lambda x: -x[1]):
        print(f"    {t:20s} {count}")
    print()

    print(f"  By status:")
    for s, count in sorted(stats["by_status"].items(), key=lambda x: -x[1]):
        print(f"    {s:20s} {count}")
    print()

    print(f"  By scope:")
    for s, count in sorted(stats["by_scope"].items(), key=lambda x: -x[1]):
        print(f"    {s:20s} {count}")
    print()

    print(f"  By project:")
    for p, count in sorted(stats["by_project"].items(), key=lambda x: -x[1]):
        print(f"    {p:20s} {count}")


def cmd_list(args: list[str]) -> None:
    """List all stored facts.

    The ``[superseded]`` label is computed from ALL facts, not just
    the filtered subset. This ensures correct display even when
    the superseding fact is outside the current filter.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="", help="Filter by fact type")
    parser.add_argument("--scope", default="", help="Filter by scope (global|project)")
    parser.add_argument("--project", default="", help="Filter by project name")
    parser.add_argument("--status", default="", help="Filter by status")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)

    # Load ALL facts to compute superseded_ids correctly
    all_facts = store.load()
    superseded_ids = {f.supersedes for f in all_facts if f.supersedes}

    # Now load with filters for display
    facts = store.load(
        fact_type=opts.type,
        scope=opts.scope,
        project=opts.project,
        status=opts.status,
    )

    # Apply confidence filter
    if opts.min_confidence:
        facts = [f for f in facts if f.confidence >= opts.min_confidence]

    # Sort by date (newest first), then confidence
    facts.sort(key=lambda f: (-f.created_at, -f.confidence))

    if not facts:
        print("[agent-memory] No facts stored")
        return

    print(f"[agent-memory] {len(facts)} facts:")
    for f in facts[:opts.limit]:
        ss = " [superseded]" if f.id in superseded_ids else ""
        status_label = f" [{f.status}]" if f.status != "active" else ""
        print(f"  {f.id[:22]:22s} [{f.type.value:18s}] {f.confidence:.0%} | "
              f"{f.scope}/{f.project or '*':6s}{status_label}{ss} | {f.content[:80]}")


def cmd_show(args: list[str]) -> None:
    """Show a single fact by ID."""
    if not args:
        print("[agent-memory] Usage: agent-memory show <id>", file=sys.stderr)
        sys.exit(1)

    fact_id = args[0]
    config = _build_config()
    store = MemoryStore(config)
    fact = store.load_by_id(fact_id)

    if not fact:
        print(f"[agent-memory] Fact not found: {fact_id}")
        return

    print(f"ID:          {fact.id}")
    print(f"Type:        {fact.type.value}")
    print(f"Confidence:  {fact.confidence:.0%}")
    print(f"Scope:       {fact.scope}")
    print(f"Project:     {fact.project or '(none)'}")
    print(f"Status:      {fact.status}")
    print(f"Content:     {fact.content}")
    print(f"Evidence:    {fact.evidence}")
    print(f"Date:        {fact.source_date}")
    print(f"Created:     {fact.created_at}")
    if fact.supersedes:
        print(f"Supersedes:  {fact.supersedes}")


def cmd_delete(args: list[str]) -> None:
    """Delete a fact by ID. Default is soft delete (marks as wrong)."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Fact ID to delete")
    parser.add_argument("--hard", action="store_true", help="Physically remove the line (default: soft delete)")
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)

    if store.delete(opts.id, hard=opts.hard):
        if opts.hard:
            print(f"[agent-memory] Permanently deleted fact: {opts.id}")
        else:
            print(f"[agent-memory] Soft-deleted fact: {opts.id} (status set to wrong)")
    else:
        print(f"[agent-memory] Fact not found: {opts.id}")


def cmd_edit(args: list[str]) -> None:
    """Edit a fact by ID.

    If content or type changes, the ID is recalculated automatically
    and the old ID is linked via ``supersedes``.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Fact ID to edit")
    parser.add_argument("--content", default=None)
    parser.add_argument("--confidence", type=float, default=None)
    parser.add_argument("--type", default=None)
    parser.add_argument("--evidence", default=None)
    parser.add_argument("--status", default=None, choices=["active", "archived", "wrong", "superseded", "proposed"])
    parser.add_argument("--scope", default=None, choices=["global", "project"])
    parser.add_argument("--project", default=None)
    opts = parser.parse_args(args)

    updates = {}
    if opts.content is not None:
        updates["content"] = opts.content
    if opts.confidence is not None:
        updates["confidence"] = opts.confidence
    if opts.type is not None:
        updates["type"] = opts.type
    if opts.evidence is not None:
        updates["evidence"] = opts.evidence
    if opts.status is not None:
        updates["status"] = opts.status
    if opts.scope is not None:
        updates["scope"] = opts.scope
    if opts.project is not None:
        updates["project"] = opts.project

    if not updates:
        print("[agent-memory] No updates specified. Use --content, --confidence, --type, --evidence, --status, --scope, or --project")
        return

    config = _build_config()
    store = MemoryStore(config)

    if store.edit(opts.id, **updates):
        print(f"[agent-memory] Updated fact: {opts.id}")
        if "content" in updates or "type" in updates:
            # Load the updated fact to show new ID
            updated = store.load_by_id(opts.id)
            if not updated:
                # Must have been recalculated — search by supersedes
                all_facts = store.load()
                for f in all_facts:
                    if f.supersedes == opts.id:
                        print(f"  New ID: {f.id}")
                        print(f"  Supersedes: {f.supersedes}")
                        break
    else:
        print(f"[agent-memory] Fact not found: {opts.id}")


def cmd_forget(args: list[str]) -> None:
    """Delete facts by keyword query."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="Keyword to search and delete")
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)

    deleted = store.forget(opts.query)
    if deleted > 0:
        print(f"[agent-memory] Deleted {deleted} fact(s) matching: {opts.query}")
    else:
        print(f"[agent-memory] No facts matching: {opts.query}")


def cmd_validate(args: list[str]) -> None:
    """Validate storage integrity."""
    config = _build_config()
    store = MemoryStore(config)
    issues = store.validate()

    if not issues:
        print("[agent-memory] Storage integrity check PASSED")
        print(f"  Directory: {store._atoms_dir}")
        stats = store.stats()
        print(f"  Facts: {stats['total_facts']}, Files: {len(list(store._atoms_dir.glob('*.jsonl')))}")
        return

    print(f"[agent-memory] Storage integrity check: {len(issues)} issue(s) found")
    for issue in issues:
        print(f"  [{issue['type']:20s}] {issue.get('file', '')}:{issue.get('line', '')} — {issue['detail']}")


def cmd_summarize(args: list[str]) -> None:
    """Generate a user profile from preference facts."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="", help="Filter to a specific topic")
    parser.add_argument("--min-confidence", type=float, default=0.7)
    parser.add_argument("--format", choices=["markdown", "text"], default="markdown")
    parser.add_argument("--save", action="store_true",
                        help="Save profile to {data_dir}/profile.md")
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)
    searcher = MemorySearch(store)

    result = searcher.summarize(
        topic=opts.topic,
        min_confidence=opts.min_confidence,
        fmt=opts.format,
    )

    if not result:
        print("[agent-memory] No preference facts found at the configured threshold")
        return

    print(result)

    if opts.save:
        from pathlib import Path
        import os
        profile_path = Path(os.path.expanduser(config.data_dir)) / "profile.md"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(result)
        print(f"[agent-memory] Profile saved to: {profile_path}")


def cmd_propose(args: list[str]) -> None:
    """Save a proposed fact (low confidence, status=proposed).

    Proposed facts are excluded from inject by default until reviewed
    and promoted to active. Use for auto-detected patterns, behavioral
    observations, or anything that needs human confirmation first.
    """
    import argparse
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="convention",
                        choices=["preference", "environment", "decision",
                                 "rejection_reason", "convention", "lesson"])
    parser.add_argument("--confidence", type=float, default=0.6)
    parser.add_argument("--evidence", default="")
    parser.add_argument("--scope", default="global")
    parser.add_argument("--project", default="")
    parser.add_argument("content", nargs="*",
                        help="The fact content (accepts multiple words)")
    opts = parser.parse_args(args)

    content = " ".join(opts.content).strip()
    if not content:
        print("[agent-memory] Usage: agent-memory propose <fact content> [--type convention]")
        return

    config = _build_config()
    store = MemoryStore(config)

    fact = AtomicFact(
        type=FactType(opts.type),
        content=content,
        confidence=max(0.0, min(opts.confidence, 0.8)),  # cap at 0.8 for proposals
        evidence=opts.evidence or "(auto-detected, pending review)",
        source_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        scope=opts.scope,
        project=opts.project,
        status="proposed",
    )

    saved = store.save([fact])
    if saved:
        print(f"[agent-memory] Proposed fact saved: {fact.id}")
        print(f"  Type: {fact.type.value} | Confidence: {int(fact.confidence * 100)}% | Status: proposed")
        print(f"  Content: {fact.content}")
        print(f"  Review: agent-memory edit {fact.id} --status active --confidence 0.9")
    else:
        print("[agent-memory] Duplicate — fact already exists")


def cmd_review(args: list[str]) -> None:
    """List all proposed facts for review."""
    config = _build_config()
    store = MemoryStore(config)

    facts = store.load(status="proposed")
    if not facts:
        print("[agent-memory] No proposed facts pending review")
        return

    # Get superseded IDs for display
    all_facts = store.load()
    superseded_ids = {f.supersedes for f in all_facts if f.supersedes}

    facts.sort(key=lambda f: (-f.confidence, -f.created_at))
    print(f"[agent-memory] {len(facts)} proposed fact(s) awaiting review:\n")
    for i, f in enumerate(facts, 1):
        ss = " [superseded?]" if f.id in superseded_ids else ""
        print(f"  {i:2d}. {f.id[:22]:22s} [{f.type.value:18s}] {f.confidence:.0%} | "
              f"{f.scope}/{f.project or '*':6s}{ss}")
        print(f"      {f.content[:120]}")
        print(f"      Evidence: {f.evidence[:80]}")
        print(f"      Accept: agent-memory accept {f.id} [--confidence 0.9]")
        print(f"      Reject: agent-memory reject {f.id}")
        print()


def cmd_accept(args: list[str]) -> None:
    """Promote a proposed fact to active."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Fact ID to accept")
    parser.add_argument("--confidence", type=float, default=0.9,
                        help="Confidence to set (default: 0.9)")
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)

    fact = store.load_by_id(opts.id)
    if not fact:
        print(f"[agent-memory] Fact not found: {opts.id}")
        return

    if fact.status != "proposed":
        print(f"[agent-memory] Fact {opts.id} is not proposed (status={fact.status})")
        return

    confidence = max(0.0, min(opts.confidence, 1.0))
    if store.edit(opts.id, status="active", confidence=confidence):
        print(f"[agent-memory] Accepted fact: {opts.id}")
        print(f"  Type: {fact.type.value} | Confidence: {int(confidence * 100)}% | Status: active")
        print(f"  Content: {fact.content}")
    else:
        print(f"[agent-memory] Failed to accept fact: {opts.id}")


def cmd_reject(args: list[str]) -> None:
    """Reject a proposed fact (set to wrong or delete)."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Fact ID to reject")
    parser.add_argument("--delete", action="store_true",
                        help="Delete instead of marking as wrong")
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)

    fact = store.load_by_id(opts.id)
    if not fact:
        print(f"[agent-memory] Fact not found: {opts.id}")
        return

    if fact.status != "proposed":
        print(f"[agent-memory] Fact {opts.id} is not proposed (status={fact.status})")
        return

    if opts.delete:
        if store.delete(opts.id):
            print(f"[agent-memory] Deleted proposed fact: {opts.id}")
        else:
            print(f"[agent-memory] Failed to delete fact: {opts.id}")
    else:
        if store.edit(opts.id, status="wrong", confidence=0.0):
            print(f"[agent-memory] Rejected fact: {opts.id}")
        else:
            print(f"[agent-memory] Failed to reject fact: {opts.id}")


def cmd_history(args: list[str]) -> None:
    """Trace the evolution history of a fact or facts matching a query."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("id", nargs="?", default="",
                        help="Fact ID to trace")
    parser.add_argument("--query", default="",
                        help="Search keyword to find facts")
    parser.add_argument("--limit", type=int, default=5,
                        help="Max results when searching by query")
    opts = parser.parse_args(args)

    if not opts.id and not opts.query:
        print("[agent-memory] Usage: agent-memory history <id> or agent-memory history --query <keyword>")
        return

    config = _build_config()
    store = MemoryStore(config)
    searcher = MemorySearch(store)

    result = searcher.history(
        fact_id=opts.id,
        query=opts.query,
        limit=opts.limit,
    )

    print(result)


def cmd_redact(args: list[str]) -> None:
    """Redact evidence text from a fact."""
    if not args:
        print("[agent-memory] Usage: agent-memory redact <id>", file=sys.stderr)
        sys.exit(1)

    fact_id = args[0]
    config = _build_config()
    store = MemoryStore(config)

    if store.edit(fact_id, evidence="[REDACTED]"):
        print(f"[agent-memory] Redacted evidence for fact: {fact_id}")
    else:
        print(f"[agent-memory] Fact not found: {fact_id}")


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="agent-memory: structured atomic fact memory for LLM agents"
    )
    parser.add_argument("command", nargs="?",
                        choices=["extract", "search", "inject", "stats",
                                 "list", "show", "delete", "edit",
                                 "forget", "validate", "redact",
                                 "summarize", "history", "propose",
                                 "review", "accept", "reject"])
    args, remaining = parser.parse_known_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "extract": cmd_extract,
        "search": cmd_search,
        "inject": cmd_inject,
        "stats": cmd_stats,
        "list": cmd_list,
        "show": cmd_show,
        "delete": cmd_delete,
        "edit": cmd_edit,
        "forget": cmd_forget,
        "validate": cmd_validate,
        "redact": cmd_redact,
        "summarize": cmd_summarize,
        "history": cmd_history,
        "propose": cmd_propose,
        "review": cmd_review,
        "accept": cmd_accept,
        "reject": cmd_reject,
    }

    commands[args.command](remaining)


if __name__ == "__main__":
    main()
