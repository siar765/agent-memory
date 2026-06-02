# Architecture

## Design Philosophy

Agent memory is not "more context." It's **better context.**

Most memory systems for LLM agents take one of two approaches:
1. **Store everything** (vector DB, full conversation history) — hits token walls immediately
2. **Store nothing** (single-session agents) — starts from zero every conversation

Agent-memory takes a third path: **extract only what matters, structure it, and evolve it.**

## The Multi-Layer Model

```
Layer 0: Raw Traces          Session JSON files (full history, never in context)
Layer 1: Atomic Facts         Structured, typed, scored (this project)
Layer 2: Narrative Summary    Human-readable daily digest (optional)
Layer 3: Persistent Notes     Manual curated key-value pairs (optional)
```

Agent-memory implements **Layer 1** — the critical bridge between raw traces and usable memory.

## Data Flow

```
Conversation Text
    │
    ▼
┌──────────────────────────────────────────────────┐
│  FactExtractor                                     │
│                                                    │
│  1. Send conversation to LLM with extraction prompt │
│  2. LLM returns JSON array of atomic facts         │
│  3. Each fact gets a content-hash ID (dedup key)   │
│  4. Facts scored by confidence (0.7-1.0)           │
│                                                    │
│  Extraction prompt engineered for:                 │
│  • Precision over recall (better miss than invent) │
│  • Eternal facts only (skip transient state)       │
│  • 6 typed categories                              │
│  • Evidence preservation (exact quote)             │
└──────────────────────┬───────────────────────────┘
                       │ list[AtomicFact]
                       ▼
┌──────────────────────────────────────────────────┐
│  MemoryStore                                       │
│                                                    │
│  • Daily JSONL shard: {date}.jsonl                │
│  • O(1) dedup via content-hash index              │
│  • Append-only writes (no locking needed)         │
│  • File-per-day means date-range queries are      │
│    O(#files), not O(#facts)                       │
│  • Zero external dependencies (pure Python)       │
│  • Human-readable, grep-able, backup-friendly     │
└──────────────────────┬───────────────────────────┘
                       │ filtered queries
                       ▼
┌──────────────────────────────────────────────────┐
│  MemorySearch                                      │
│                                                    │
│  • Keyword matching on content                     │
│  • Type filtering (6 categories)                   │
│  • Date range filtering (file-level)               │
│  • Confidence threshold filtering                  │
│  • Sorted: high confidence → newest first          │
│                                                    │
│  inject_summary():                                 │
│  • Selects top N facts above confidence threshold  │
│  • Formats as compact markdown                     │
│  • Ready for system prompt injection               │
│  • Designed to consume <2KB of context window      │
└──────────────────────────────────────────────────┘
```

## The 6 Fact Types — Why These Six

The type system emerged from analyzing what LLM agents actually need to remember:

| Type | What it solves | Anti-pattern without it |
|------|---------------|------------------------|
| `preference` | "Stop suggesting things I already said I hate" | Agent re-recommends rejected options |
| `environment` | "Stop trying things I told you don't work" | Agent wastes tokens on known-dead ends |
| `decision` | "Remember which path I chose" | Agent asks the same question again |
| `rejection_reason` | "Remember WHY I said no" | Agent re-proposes rejected alternatives |
| `convention` | "Be consistent with how we do things" | Agent uses wrong patterns |
| `lesson` | "Don't make the same mistake twice" | Agent repeats known-expensive errors |

## Confidence Scoring

```
1.0  →  Explicitly stated by user ("I prefer...")
0.9  →  Strongly implied by context ("CLI is much better than GUI")
0.8  →  Inferred from behavior pattern (user chose CLI 5 times in a row)
<0.8 →  Speculative — stored but NOT auto-injected
```

The `inject_threshold` (default 0.8) ensures only high-certainty facts
consume context window space. Low-confidence facts remain searchable
but don't pollute the prompt.

## Evolution Tracking

Facts can be superseded without deletion:

```
+---------+          +---------+
| Old fact |──supersedes──▶| New fact |
+---------+   pointer     +---------+
```

The `supersedes` field links to the previous fact's ID. This preserves
the history of how understanding evolved while keeping only the current
truth in the injection summary.

## Storage Format

```
~/.agent/memory/atoms/
├── 2026-06-01.jsonl
├── 2026-06-02.jsonl
└── 2026-06-03.jsonl
```

Each file is append-only JSONL. Line-level format:

```json
{"id":"a1b2...","type":"preference","content":"...","confidence":1.0,
 "evidence":"User said: '...'","source_date":"2026-06-01",
 "supersedes":"","created_at":1748880000.0}
```

Benefits of this format:
- **Append-only** → concurrent writers don't conflict
- **Daily shards** → time-range queries filter at filesystem level
- **Plain text** → grep/sed/awk compatible
- **No DB driver** → zero deployment dependencies
- **Git-friendly** → trivial to version control

## Dependencies

- **Runtime**: Python 3.10+ standard library (zero pip dependencies)
- **Extraction**: Any OpenAI-compatible API (tested with OpenAI, DeepSeek, Claude)
- **Storage**: Filesystem (local, NFS, Docker volumes)

No vector database. No graph database. No embedding model. No Redis.
Just Python, files, and an LLM you already have.
