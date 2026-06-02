"""
Command-line interface for agent-memory.

Usage::

    # Extract facts from a conversation file
    echo "..." | agent-memory extract

    # Search stored facts
    agent-memory search --query "preference" --type preference

    # Generate injection summary
    agent-memory inject --query "docker"

    # Manage facts
    agent-memory list
    agent-memory show <id>
    agent-memory delete <id>
    agent-memory edit <id> --content "new text"
    agent-memory forget --query "old info"

    # Validate storage integrity
    agent-memory validate

    # View stats
    agent-memory stats
"""

from __future__ import annotations

import sys
from pathlib import Path

from .core import MemoryConfig
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

    saved = store.save(facts)

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
        print(f"  [{f.type.value:18s}] {f.confidence:.0%} | {f.content}")

    if len(facts) > saved:
        print(f"  ({len(facts) - saved} duplicates skipped)")


def cmd_search(args: list[str]) -> None:
    """Search stored facts."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--type", default="")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--no-bm25", action="store_true", help="Disable BM25 ranking")
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)
    searcher = MemorySearch(store)

    facts = searcher.search(
        query=opts.query,
        fact_type=opts.type,
        limit=opts.limit,
        min_confidence=opts.min_confidence,
        use_bm25=not opts.no_bm25,
    )

    if not facts:
        print("[agent-memory] No matching facts")
        return

    print(f"[agent-memory] {len(facts)} matching facts:")
    for f in facts:
        print(f"  [{f.type.value:18s}] {f.confidence:.0%} | {f.source_date} | {f.content}")


def cmd_inject(args: list[str]) -> None:
    """Generate injection summary for system prompt."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--min-confidence", type=float, default=0.8)
    parser.add_argument("--date-from", default="")
    parser.add_argument("--query", default="", help="Task context for relevance ranking")
    parser.add_argument("--all", action="store_true", help="Include superseded facts too")
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


def cmd_list(args: list[str]) -> None:
    """List all stored facts."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="", help="Filter by fact type")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)
    searcher = MemorySearch(store)

    facts = searcher.search(
        fact_type=opts.type,
        limit=opts.limit,
        min_confidence=opts.min_confidence,
        use_bm25=False,
    )

    if not facts:
        print("[agent-memory] No facts stored")
        return

    print(f"[agent-memory] {len(facts)} facts:")
    for f in facts:
        ss = " [superseded]" if f.supersedes else ""
        print(f"  {f.id[:20]:20s} [{f.type.value:18s}] {f.confidence:.0%} | {f.content[:80]}{ss}")


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
    print(f"Content:     {fact.content}")
    print(f"Evidence:    {fact.evidence}")
    print(f"Date:        {fact.source_date}")
    print(f"Created:     {fact.created_at}")
    if fact.supersedes:
        print(f"Supersedes:  {fact.supersedes}")


def cmd_delete(args: list[str]) -> None:
    """Delete a fact by ID."""
    if not args:
        print("[agent-memory] Usage: agent-memory delete <id>", file=sys.stderr)
        sys.exit(1)

    fact_id = args[0]
    config = _build_config()
    store = MemoryStore(config)

    if store.delete(fact_id):
        print(f"[agent-memory] Deleted fact: {fact_id}")
    else:
        print(f"[agent-memory] Fact not found: {fact_id}")


def cmd_edit(args: list[str]) -> None:
    """Edit a fact by ID."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Fact ID to edit")
    parser.add_argument("--content", default=None)
    parser.add_argument("--confidence", type=float, default=None)
    parser.add_argument("--type", default=None)
    parser.add_argument("--evidence", default=None)
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

    if not updates:
        print("[agent-memory] No updates specified. Use --content, --confidence, --type, or --evidence")
        return

    config = _build_config()
    store = MemoryStore(config)

    if store.edit(opts.id, **updates):
        print(f"[agent-memory] Updated fact: {opts.id}")
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
                                 "forget", "validate", "redact"])
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
    }

    commands[args.command](remaining)


if __name__ == "__main__":
    main()
