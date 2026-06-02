
  <p align="center">
    <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-light.svg#gh-light-mode-only">
    <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-dark.svg#gh-dark-mode-only">
  </p>

  <h3 align="center">Your agent shouldn't forget who you are every three weeks</h3>

  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/github/license/siar765/agent-memory?style=flat-square" alt="License"></a>
    <a href="https://github.com/siar765/agent-memory/releases/tag/v1.0.0-beta.3"><img src="https://img.shields.io/badge/status-beta-yellow?style=flat-square" alt="Beta"></a>
    <a href="#zero-dependencies"><img src="https://img.shields.io/badge/dependencies-zero-brightgreen?style=flat-square" alt="Zero dependencies"></a>
    <a href="https://github.com/siar765/agent-memory/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/siar765/agent-memory/test.yml?style=flat-square&label=tests" alt="Tests"></a>
    <a href="https://github.com/siar765/agent-memory/stargazers"><img src="https://img.shields.io/github/stars/siar765/agent-memory?style=flat-square" alt="Stars"></a>
    <a href="DISCLAIMER.md"><img src="https://img.shields.io/badge/disclaimer-legal-lightgrey?style=flat-square" alt="Disclaimer"></a>
  </p>
</p>

**Zero external dependencies.** No vector DB. No cloud service. No hidden state.
Every memory is a line in a text file you can grep.

**Agent-memory is a structured, editable memory layer for personal AI agents.** It extracts durable facts from conversations — what you like, what you decided, what doesn't work — stores them as typed, confidence-scored entries in plain JSONL, and injects only relevant ones into your agent's system prompt. Your agent remembers you, session after session, without token bloat or black-box vector databases.

---

## The problem

When you first start working with an AI agent, it feels like magic. It remembers your preferences, your project decisions, the things you told it last week.

**Three weeks later, it's a stranger.**

The agent's context window fills up. Old memories get compressed into a blurry summary. You find yourself repeating things you've already said — *"I told you, I prefer CLI over GUI"* — and the agent nods politely, then forgets again.

Existing memory systems try to solve this, but they're designed for *enterprise multi-user SaaS*, not for one person running an agent on their laptop:

> **mem0** — needs a cloud API, couples you to their platform  
> **Graphiti** — knowledge graph infra, overkill for personal use  
> **LangMem** — requires the entire LangChain ecosystem  
> **Hy-Memory** — locked into OpenClaw framework

What if memory was just... a text file?

---

## Enter agent-memory

```bash
pip install git+https://github.com/siar765/agent-memory.git
# No server or database required. Extraction requires an LLM API key (see Quick start).
```

Agent-memory is a **local-first, editable memory layer** for personal AI agents. It extracts durable facts from conversations — what you like, what you decided, what doesn't work — and stores them as plain JSONL.

```bash
# Extract facts from a conversation
echo "User: I use VS Code for Python, Neovim for everything else" | \
  agent-memory extract

# Search what the agent remembers
agent-memory search --query "editor preference"

# Inject relevant memories into your agent's system prompt
agent-memory inject --query "project context"
```

**Output:**
```
$ agent-memory list
 pr:4a1b2c3d    preference   active   "Prefers CLI over GUI for system tasks"
 en:5e6f7a8b    environment  active   "Docker 443 blocked, no git clone over HTTPS"
 dc:9c0d1e2f    decision     active   "Using PostgreSQL for blog project"
 rr:3a4b5c6d    rejection    active   "Ruled out MongoDB — too heavy for NAS"
 co:7e8f9a0b    convention   active   "Chinese for design docs, English for code"
 le:1c2d3e4f    lesson       active   "Don't run apt upgrade before cron jobs"
```

---

## What makes it different

**It's just JSONL** — every memory is one line in a text file. You can `grep` it, `jq` it, back it up with `rsync`, version it with git.

**6 fact types** — not a blob of text. Every memory knows what it is:

| Type | What it captures |
|---|---|
| `preference` 💡 | User likes, dislikes, habits |
| `environment` 🔧 | System constraints, network limits |
| `decision` ✅ | Explicit choices with rationale |
| `rejection_reason` ❌ | What was ruled out and why |
| `convention` 📐 | Recurring patterns, practices |
| `lesson` 📝 | Mistakes, corrections, insights |

**Editable** — wrong memory? Fix it:

```bash
agent-memory edit pr:4a1b2c3d --content "User prefers VS Code now"
agent-memory delete pr:old_obsolete_fact
agent-memory redact pr:sensitive_fact  # mask evidence, keep the fact
agent-memory forget --query "old information i no longer need"
```

**Project-scoped** — work memories don't leak into your personal context:

```bash
agent-memory extract --scope project --project blog
agent-memory inject --scope project --project blog --include-global
# --include-global merges global preferences with project-specific facts
```

**Evolution chain** — correct a fact without losing history. The old fact is preserved as `superseded`, the new one links back:

```
[Old] "Prefers dark mode"  ──supersedes──→ [New] "Now prefers light mode"
    status=superseded                           status=active
                                ↕
              inject/search default to active, exclude superseded/proposed
```

**Review gate** — auto-detected patterns land as `proposed` facts, kept out of your agent's prompt until you review:

```bash
agent-memory propose "User checks crypto prices daily" --type convention
agent-memory list --status proposed   # review pending proposals
agent-memory accept pr:xxx --confidence 0.9  # promote to active
agent-memory reject pr:xxx           # discard
```

---

## Real-world numbers

Been running 24/7 since May 2026, powering 80+ automated daily tasks on a NAS:

| Metric | Value |
|---|---|
| Facts extracted per day | ~25 |
| Inject size for system prompt | ~1-2 KB (15 active facts) |
| Extraction time per conversation | ~1.5s (gpt-4o-mini) |
| Storage method | JSONL, grep-able |
| External dependencies | **Zero** |
| Dedup after startup | O(1) |

---

## Architecture in 30 seconds

```
Conversation text
       ↓
  [LLM extractor]  ← typed, scoped, confidence-scored
       ↓
  [JSONL storage]  ← one file per day, grep-able, git-versionable
       ↓
  [BM25 search]    ← zero-dependency ranking, CJK support
       ↓
  [Inject summary] → system prompt (1-2 KB, not 50 KB)
```

Key design decisions:
- **No vector DB** — personal-scope memory (<10K facts) doesn't need it
- **No dependencies** — pure Python stdlib. Install anywhere.
- **No hidden state** — every fact is visible, editable, deletable
- **Atomic writes** — file lock + `os.replace()`, no corruption

---

## Quick start

```bash
# 1. Install
pip install git+https://github.com/siar765/agent-memory.git
export LLM_API_KEY="sk-..."  # any OpenAI-compatible provider
export LLM_MODEL="gpt-4o-mini"

# 2. Extract memories from a conversation
echo "User: We use PostgreSQL for this project." | agent-memory extract
echo "User: I prefer CLI over GUI for everything." | agent-memory extract --scope global

# 3. Search what's stored
agent-memory search "prefer editor"
agent-memory list --type preference

# 4. Generate injection summary for your agent's system prompt
agent-memory inject --scope project --project blog --limit 10

# 5. Fix mistakes
agent-memory edit pr:4a1b2c3d --content "Updated preference"
agent-memory delete pr:obsolete_entry
```

---

## Comparison

| | agent-memory | mem0 | Graphiti | LangMem | Hy-Memory |
|---|---|---|---|---|---|
| Dependencies | **Zero** | cloud API + deps | neo4j + infra | LangChain | OpenClaw |
| Local-first | ✅ | ❌ | ❌ | ✅ | ✅ |
| Editable facts | ✅ | ❌ | ⚠️ | ⚠️ | ❌ |
| Evolution chain | ✅ | ❌ | ✅ | ❌ | ✅ |
| Review gate (propose→accept/reject) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Project isolation + global merge | ✅ | ❌ | ❌ | ❌ | ✅ |
| File format | JSONL (grep-able) | proprietary | graph DB | proprietary | proprietary |
| Single-user | ✅ (targeted) | ❌ (multi-user) | ❌ (enterprise) | ❌ (framework) | ✅ |

---

## Known Limitations (beta)

| Area | Status |
|---|---|
| **Vector search** | Not needed. Personal-scope memory (<10K facts) works fine with BM25. |
| **Multi-user** | Single-user only. No per-user isolation — scope/project is the only partitioning. |
| **Concurrent writes** | File-locked per-write. Not designed for parallel agent swarms writing to the same store. |
| **Migration tooling** | No `import-from` for mem0/Graphiti/LangMem formats yet. JSONL is intentionally simple for manual migration. |
| **API stability** | CLI flags and fact schema may change before v1.0.0. The JSONL format itself is stable and backward-readable. |

If these are blockers, [open an issue](https://github.com/siar765/agent-memory/issues).

---

## License

MIT
