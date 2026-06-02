# agent-memory: Design & Philosophy

## Why six fact types?

Agent-memory organizes extracted facts into exactly six categories. This is a deliberate constraint, not a limitation. Every type was chosen because it answers a specific question that agents repeatedly need to answer:

| Type | Answers | Why it exists separately |
|------|---------|------------------------|
| **preference** | What does the user like? | Shortest-lived, most frequently updated, highest injection priority |
| **environment** | What constraints exist? | Changes rarely, affects every decision, must be stable |
| **decision** | What was chosen and why? | Prevents re-debate, saves token cost, records rationale |
| **rejection_reason** | What was ruled out and why? | Most commonly forgotten — agents keep suggesting rejected options |
| **convention** | How do we do things here? | Pattern recognition over time, emerges from repeated behavior |
| **lesson** | What went wrong? | Highest long-term value, most stable, rarest to update |

### What NOT to extract

Equally important are the boundaries. The following are deliberately excluded from durable memory:

- **Transient states** ("User is tired", "User is working on project X") — change too fast
- **Emotional states** ("User is frustrated") — unreliable, contextual
- **Procedural instructions** ("Run `pip install`") — belong in code/scripts
- **Session-specific context** ("We talked about Y earlier") — belongs in conversation history
- **Speculative preferences** — must be explicitly stated or strongly implied, not guessed

## Boundary cases

### preference vs decision

A preference becomes a decision only when an explicit choice is made between alternatives:

```
"I prefer Python"                              → preference
"I chose Python over Java for this project"    → decision + preference
"I chose Python because I prefer its syntax"   → decision (with reasoning)
```

If there's no alternative, it's a preference. If there's a choice with a trade-off, it's a decision.

### environment vs convention

An environment is a hard constraint. A convention is a soft rule that could be changed:

```
"Docker port 443 is blocked"    → environment (can't change)
"We name files as snake_case"   → convention (could change, but we don't)
"GitHub Actions is free for public repos" → environment
"We always run tests before push" → convention
```

### rejection_reason vs decision

A decision records what was chosen. A rejection records what was NOT chosen and why:

```
"Chose PostgreSQL over MySQL"             → decision (what was picked)
"Rejected MongoDB — too complex"          → rejection_reason (what was not picked + why)
"Chose PostgreSQL over MySQL because... " → both (decision + rejection_reason in context)
```

Both may apply to the same conversation turn, but they are stored as separate facts because they serve different purposes: decisions guide future choices, rejections prevent re-suggesting.

### lesson vs convention

A lesson is learned from a specific failure. A convention emerges from successful repetition:

```
"patch tool double-escapes JSON — always use write_file instead"   → lesson
"We always write files with write_file, never patch for JSON"      → convention
```

A lesson becomes a convention after it's been practiced consistently. Both are kept because the lesson preserves the "why" while the convention preserves the "what".

## The confidence model

Confidence is not a probability. It's a pragmatic signal for the agent:

| Score | Meaning | Injection behavior |
|-------|---------|-------------------|
| 1.0 | Explicitly stated by user | Always inject (unless superseded) |
| 0.9 | Strongly implied by context | Inject if relevant |
| 0.8 | Inferred from behavior pattern | Inject only if strongly relevant |
| <0.7 | Discarded | Never stored |

The hard floor at 0.7 is intentional: anything below is noise, not signal.

## Evolution tracking

Facts change. The supersedes chain records that history:

```
[2026-05-01] preference: "User prefers Vim"    (id: abc123)
[2026-05-15] preference: "User switched to VS Code"  (id: def456, supersedes: abc123)
```

In injection, only the active (non-superseded) fact appears. The old fact is retained for audit and recovery.

Currently, supersedes links must be set explicitly or by the extractor when it detects a correction. Automatic conflict detection is a future goal.

## Retrieval philosophy

Agent-memory is not a vector database. It does not do semantic search. This is by design:

- **Keyword search** is predictable and debuggable — you know exactly why a fact matched
- **BM25** (when enabled) adds term-frequency awareness without external dependencies
- **Type + confidence + date filters** give structured access that vector search cannot provide

For semantic recall, agent-memory can be paired with any embedding service. The injection API accepts external enrichment.

## Why not [X]?

### Why not vector search?

Vector search is powerful but introduces: embedding model dependency, storage overhead, unpredictable recall, and debugging difficulty. Agent-memory prioritizes **deterministic retrieval** over **fuzzy recall**. If you need semantic search, pipe agent-memory facts into any vector store.

### Why not a database?

PostgreSQL, SQLite, and friends add deployment complexity. JSONL is:
- Greppable with standard Unix tools
- Backup-friendly (cp/scp the file)
- Version-controllable (git tracks changes)
- Editable in any text editor
- Zero configuration

The trade-off is write throughput. For single-user/single-agent workloads (<100 facts/day), this is negligible.

### Why not multi-user?

Namespaces and multi-tenancy are important but add complexity that distracts from the core memory model. Agent-memory is a **single-user memory layer**. Multi-user isolation can be built on top by setting different `data_dir` values.

## What agent-memory IS and ISN'T

| It is | It is not |
|-------|-----------|
| A durable fact logger | A full agent memory system |
| A retrieval layer for system prompts | A conversation history store |
| A quality gate for what agents remember | A vector database |
| A lightweight, auditable, zero-dep library | An enterprise memory backend |
| A tool for personal/coding agents | A multi-tenant shared memory service |

This clarity of scope is intentional. Agent-memory does one thing and does it well: **extract, store, retrieve, and inject high-quality atomic facts for LLM agents.**
