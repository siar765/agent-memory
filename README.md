
  <p align="center">
    <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-light.svg#gh-light-mode-only">
    <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-dark.svg#gh-dark-mode-only">
  </p>

  <h3 align="center">Local-first, editable memory layer for personal AI agents</h3>

  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/github/license/siar765/agent-memory?style=flat-square" alt="License"></a>
    <a href="https://github.com/siar765/agent-memory/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/siar765/agent-memory/test.yml?style=flat-square&label=tests" alt="Tests"></a>
    <a href="https://github.com/siar765/agent-memory/stargazers"><img src="https://img.shields.io/github/stars/siar765/agent-memory?style=flat-square" alt="Stars"></a>
    <a href="SECURITY.md"><img src="https://img.shields.io/badge/security-policy-blue?style=flat-square" alt="Security"></a>
    <a href="DISCLAIMER.md"><img src="https://img.shields.io/badge/disclaimer-legal-lightgrey?style=flat-square" alt="Disclaimer"></a>
  </p>
</p>

Agent-memory is a local-first, editable, JSONL-based memory layer for personal AI agents. It extracts durable facts from conversations — preferences, environment constraints, decisions, rejected options, conventions, and lessons — then stores them as plain JSONL files you can inspect, edit, delete, grep, or back up.

No vector database. No service to run. No hidden state. Every memory is a line in a text file.

---

## Why this exists

Most agent memory systems try to store everything and figure out relevance later. In practice this means:

- **Token bloat** — the system prompt grows until it hurts
- **Black box** — you can't see what the agent remembers about you
- **No correction** — wrong memories persist because you can't delete them
- **Cross-project pollution** — work-related facts leak into personal context

Agent-memory takes a different path:

| Problem | Naive approach | Agent-memory |
|---|---|---|
| What to store | Everything (vector dump) | Only **durable, typed facts** worth remembering |
| Facts changing | Overwrite or version hell | **Supersedes chain** — new facts link to what they replaced, inject filters out old ones |
| Evidence trail | Gone after extraction | **Source evidence** preserved — every fact traces back to exact conversation text |
| Token cost | O(entire history) per query | **O(atomic summary)** — injects only 1-2KB, not 50KB |
| Correction | Can't delete wrong memories | **CLI: delete, edit, forget, redact** — full governance |

---

## 6 fact types

| Type | What it captures | Why you need it |
|---|---|---|
| `preference` 💡 | User likes, dislikes, habits, style | Agent stops asking "dark or light mode?" |
| `environment` 🔧 | System constraints, network limits, config | Agent stops suggesting solutions that can't work here |
| `decision` ✅ | Explicit choices, with rationale | Agent doesn't re-debate settled decisions |
| `rejection_reason` ❌ | What was ruled out and why | Agent stops suggesting the same rejected option |
| `convention` 📐 | Recurring patterns, team practices | Agent follows your project standards |
| `lesson` 📝 | Mistakes, corrections, hard-won insights | Agent doesn't repeat your past failures |

---

## Install

```bash
pip install git+https://github.com/siar765/agent-memory.git
```

---

## Quick start

```bash
# Export an API key
export LLM_API_KEY="sk-..."  # any OpenAI-compatible provider
export LLM_MODEL="gpt-4o-mini"

# Extract facts from a conversation
echo "User: I prefer CLI over GUI for everything." | agent-memory extract

# Extract with project scoping
echo "User: We use PostgreSQL for this project." | agent-memory extract --scope project --project blog

# Generate injection summary for system prompt
agent-memory inject
agent-memory inject --query "deploy docker" --scope project --project blog

# Inspect stored facts
agent-memory list
agent-memory list --scope project --project blog

# Manage facts
agent-memory show pr:abc123def45678
agent-memory delete pr:abc123def45678
agent-memory edit pr:abc123def45678 --content "User prefers VS Code now"
agent-memory forget --query "old information"
agent-memory redact pr:abc123def45678  # mask evidence

# Validate storage integrity
agent-memory validate

# Storage stats
agent-memory stats
```

---

## Real-world usage pattern

```
# 1. End of day: extract facts from today's conversations
cat sessions/*.json | agent-memory extract --scope project --project agent-memory

# 2. Before each agent session: inject relevant memories
inject_summary=$(agent-memory inject --query "context for today's task" --scope project --project blog --limit 10)

# 3. The agent prompt includes only high-confidence, active, relevant facts
system_prompt = f"You are a helpful assistant. User context: {inject_summary}"
```

---

## Project scoping

Facts belong to a **scope** (`global` or `project`) and optionally a **project name**.

```bash
agent-memory extract --scope global          # applies everywhere
agent-memory extract --scope project --project agent-memory  # project-specific
agent-memory inject --scope project --project blog
```

This prevents cross-project pollution — your blog project's "use PostgreSQL" decision
won't conflict with your general "avoid heavy dependencies" preference.

---

## Lifecycle: status & supersedes

Every fact has a `status`:
- `active` — current and trustworthy (default)
- `archived` — still true but no longer relevant
- `wrong` — confirmed incorrect
- `superseded` — replaced by a newer fact

When you correct a fact (`agent-memory edit --content "new"`), the old ID is
automatically linked via `supersedes`. Search and inject default to `active` only.

---

## Performance

Agent-memory has been running 24/7 since May 2026, powering
80+ automated tasks daily on personal hardware. Metrics from real operation:

- **~25 facts extracted per day** from daily conversation summaries
- **O(1) dedup** after startup index rebuild
- **~1-2KB inject size** for a system prompt with 15 active facts
- **~1.5s extraction time** per daily conversation (gpt-4o-mini)

---

## Architecture

See [ARCHITECTURE.md](docs/architecture.md) and [DESIGN.md](docs/design.md).

Key design decisions:
- **JSONL files** — grep-able, backup-able, git-versionable, no service dependency
- **BM25 search** — zero-dependency term-frequency ranking with CJK support
- **No vector DB** — not needed for personal-scope memory (typically <10K facts)
- **Rule-based self-critique** — validates evidence factuality without additional LLM calls

---

## Why not mem0 / Graphiti / LangMem?

Those projects solve different problems:

- **mem0** — multi-user, multi-agent, cloud-native memory. Overkill for a single user.
- **Graphiti** — knowledge graph-based memory for enterprise agents. Complex infra.
- **LangMem** — LangChain ecosystem memory. Tightly coupled to LangChain.

Agent-memory is for the **personal agent running on a laptop or NAS** — where simplicity,
auditability, and zero dependencies matter more than scale.

---

## License

MIT
