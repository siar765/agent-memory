"""
Command-line interface for agent-memory.

Usage::

    # Extract facts from a conversation file
    echo "..." | agent-memory extract

    # Search stored facts
    agent-memory search --query "preference" --type preference

    # Generate injection summary
    agent-memory inject

    # View stats
    agent-memory stats
"""

from __future__ import annotations

import sys
from pathlib import Path

from .core import MemoryConfig
from .extractor import FactExtractor
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
    extractor = FactExtractor(config)
    store = MemoryStore(config)

    facts = extractor.extract(text)
    if not facts:
        print("[agent-memory] No facts extracted")
        return

    saved = store.save(facts)
    print(f"[agent-memory] Extracted {len(facts)} facts, saved {saved} new")
    for f in facts:
        print(f"  [{f.type.value:18s}] {f.confidence:.0%} | {f.content}")


def cmd_search(args: list[str]) -> None:
    """Search stored facts."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--type", default="")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)
    searcher = MemorySearch(store)

    facts = searcher.search(
        query=opts.query,
        fact_type=opts.type,
        limit=opts.limit,
        min_confidence=opts.min_confidence,
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
    opts = parser.parse_args(args)

    config = _build_config()
    store = MemoryStore(config)
    searcher = MemorySearch(store)

    summary = searcher.inject_summary(
        limit=opts.limit,
        min_confidence=opts.min_confidence,
        date_from=opts.date_from,
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
    print(f"  Total facts:    {stats['total_facts']}")
    print(f"  Storage used:   {stats['storage_bytes']:,} bytes")
    print(f"  Data directory: {stats['data_dir']}")
    print()
    print(f"  By type:")
    for t, count in sorted(stats["by_type"].items(), key=lambda x: -x[1]):
        print(f"    {t:20s} {count}")


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="agent-memory: structured atomic fact memory for LLM agents"
    )
    parser.add_argument("command", nargs="?", default="stats",
                        choices=["extract", "search", "inject", "stats"])
    args, remaining = parser.parse_known_args()

    commands = {
        "extract": cmd_extract,
        "search": cmd_search,
        "inject": cmd_inject,
        "stats": cmd_stats,
    }

    commands[args.command](remaining)


if __name__ == "__main__":
    main()
