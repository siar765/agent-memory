     1|
     2|  <p align="center">
     3|    <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-light.svg#gh-light-mode-only">
     4|    <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-dark.svg#gh-dark-mode-only">
     5|  </p>
     6|
     7|  <h3 align="center">Local-first, editable memory layer for personal AI agents</h3>
     8|
     9|  <p align="center">
    10|    <a href="LICENSE"><img src="https://img.shields.io/github/license/siar765/agent-memory?style=flat-square" alt="License"></a>
    <a href="https://github.com/siar765/agent-memory/releases/tag/v1.0.0-beta.1"><img src="https://img.shields.io/badge/status-beta-yellow?style=flat-square" alt="Beta"></a>
    <a href="#install"><img src="https://img.shields.io/badge/dependencies-zero-brightgreen?style=flat-square" alt="Zero dependencies"></a>
    11|    <a href="https://github.com/siar765/agent-memory/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/siar765/agent-memory/test.yml?style=flat-square&label=tests" alt="Tests"></a>
    12|    <a href="https://github.com/siar765/agent-memory/stargazers"><img src="https://img.shields.io/github/stars/siar765/agent-memory?style=flat-square" alt="Stars"></a>
    13|    <a href="SECURITY.md"><img src="https://img.shields.io/badge/security-policy-blue?style=flat-square" alt="Security"></a>
    14|    <a href="DISCLAIMER.md"><img src="https://img.shields.io/badge/disclaimer-legal-lightgrey?style=flat-square" alt="Disclaimer"></a>
    15|  </p>
    16|</p>
    17|
    18|Agent-memory is a local-first, editable, JSONL-based memory layer for personal AI agents. It extracts durable facts from conversations — preferences, environment constraints, decisions, rejected options, conventions, and lessons — then stores them as plain JSONL files you can inspect, edit, delete, grep, or back up.
    19|
    20|No vector database. No service to run. No hidden state. Every memory is a line in a text file.

> ⚠️ **Beta** — core API stable, tested in production since May 2026. Breaking changes possible before v1.0.0. Focused on correctness, not yet on migration tooling or v1.0 API guarantees.
    21|
    22|---
    23|
    24|## Why this exists
    25|
    26|Most agent memory systems try to store everything and figure out relevance later. In practice this means:
    27|
    28|- **Token bloat** — the system prompt grows until it hurts
    29|- **Black box** — you can't see what the agent remembers about you
    30|- **No correction** — wrong memories persist because you can't delete them
    31|- **Cross-project pollution** — work-related facts leak into personal context
    32|
    33|Agent-memory takes a different path:
    34|
    35|| Problem | Naive approach | Agent-memory |
    36||---|---|---|
    37|| What to store | Everything (vector dump) | Only **durable, typed facts** worth remembering |
    38|| Facts changing | Overwrite or version hell | **Supersedes chain** — new facts link to what they replaced, inject filters out old ones |
    39|| Evidence trail | Gone after extraction | **Source evidence** preserved — every fact traces back to exact conversation text |
    40|| Token cost | O(entire history) per query | **O(atomic summary)** — injects only 1-2KB, not 50KB |
    41|| Correction | Can't delete wrong memories | **CLI: delete, edit, forget, redact** — full governance |
    42|
    43|---
    44|
    45|## 6 fact types
    46|
    47|| Type | What it captures | Why you need it |
    48||---|---|---|
    49|| `preference` 💡 | User likes, dislikes, habits, style | Agent stops asking "dark or light mode?" |
    50|| `environment` 🔧 | System constraints, network limits, config | Agent stops suggesting solutions that can't work here |
    51|| `decision` ✅ | Explicit choices, with rationale | Agent doesn't re-debate settled decisions |
    52|| `rejection_reason` ❌ | What was ruled out and why | Agent stops suggesting the same rejected option |
    53|| `convention` 📐 | Recurring patterns, team practices | Agent follows your project standards |
    54|| `lesson` 📝 | Mistakes, corrections, hard-won insights | Agent doesn't repeat your past failures |
    55|
    56|---
    57|
    58|## Install
    59|
    60|```bash
    61|pip install git+https://github.com/siar765/agent-memory.git
    62|```
    63|
    64|---
    65|
    66|## Quick start
    67|
    68|```bash
    69|# Export an API key
    70|export LLM_API_KEY="***"  # any OpenAI-compatible provider
    71|export LLM_MODEL="gpt-4o-mini"
    72|
    73|# Extract facts from a conversation
    74|echo "User: I prefer CLI over GUI for everything." | agent-memory extract
    75|
    76|# Extract with project scoping
    77|echo "User: We use PostgreSQL for this project." | agent-memory extract --scope project --project blog
    78|
    79|# Generate injection summary for system prompt
    80|agent-memory inject
    81|agent-memory inject --query "deploy docker" --scope project --project blog
    82|
    83|# Inspect stored facts
    84|agent-memory list
    85|agent-memory list --scope project --project blog
    86|
    87|# Manage facts
    88|agent-memory show pr:abc123def45678
    89|agent-memory delete pr:abc123def45678
    90|agent-memory edit pr:abc123def45678 --content "User prefers VS Code now"
    91|agent-memory forget --query "old information"
    92|agent-memory redact pr:abc123def45678  # mask evidence
    93|
    94|# Validate storage integrity
    95|agent-memory validate
    96|
    97|# Storage stats
    98|agent-memory stats
    99|```
   100|
   101|---
   102|
   103|## Real-world usage pattern
   104|
   105|```
   106|# 1. End of day: extract facts from today's conversations
   107|cat sessions/*.json | agent-memory extract --scope project --project agent-memory
   108|
   109|# 2. Before each agent session: inject relevant memories
   110|inject_summary=$(agent-memory inject --query "context for today's task" --scope project --project blog --limit 10)
   111|
   112|# 3. The agent prompt includes only high-confidence, active, relevant facts
   113|system_prompt = f"You are a helpful assistant. User context: {inject_summary}"
   114|```
   115|
   116|---
   117|
   118|## Project scoping
   119|
   120|Facts belong to a **scope** (`global` or `project`) and optionally a **project name**.
   121|
   122|```bash
   123|agent-memory extract --scope global          # applies everywhere
   124|agent-memory extract --scope project --project agent-memory  # project-specific
   125|agent-memory inject --scope project --project blog
   126|```
   127|
   128|This prevents cross-project pollution — your blog project's "use PostgreSQL" decision
   129|won't conflict with your general "avoid heavy dependencies" preference.
   130|
   131|---
   132|
   133|## Lifecycle: status & supersedes
   134|
   135|Every fact has a `status`:
   136|- `active` — current and trustworthy (default)
   137|- `archived` — still true but no longer relevant
   138|- `wrong` — confirmed incorrect
   139|- `superseded` — replaced by a newer fact
   140|
   141|When you correct a fact (`agent-memory edit --content "new"`), the old ID is
   142|automatically linked via `supersedes`. Search and inject default to `active` only.
   143|
   144|---
   145|
   146|## Performance
   147|
   148|Agent-memory has been running 24/7 since May 2026, powering
   149|80+ automated tasks daily on personal hardware. Metrics from real operation:
   150|
   151|- **~25 facts extracted per day** from daily conversation summaries
   152|- **O(1) dedup** after startup index rebuild
   153|- **~1-2KB inject size** for a system prompt with 15 active facts
   154|- **~1.5s extraction time** per daily conversation (gpt-4o-mini)
   155|
   156|---
   157|
   158|## Architecture
   159|
   160|See [ARCHITECTURE.md](docs/architecture.md) and [DESIGN.md](docs/design.md).
   161|
   162|Key design decisions:
   163|- **JSONL files** — grep-able, backup-able, git-versionable, no service dependency
   164|- **BM25 search** — zero-dependency term-frequency ranking with CJK support
   165|- **No vector DB** — not needed for personal-scope memory (typically <10K facts)
   166|- **Rule-based self-critique** — validates evidence factuality without additional LLM calls
   167|
   168|---
   169|
   170|## Why not mem0 / Graphiti / LangMem?
   171|
   172|Those projects solve different problems:
   173|
   174|- **mem0** — multi-user, multi-agent, cloud-native memory. Overkill for a single user.
   175|- **Graphiti** — knowledge graph-based memory for enterprise agents. Complex infra.
   176|- **LangMem** — LangChain ecosystem memory. Tightly coupled to LangChain.
   177|
   178|Agent-memory is for the **personal agent running on a laptop or NAS** — where simplicity,
   179|auditability, and zero dependencies matter more than scale.
   180|
   181|---
   182|
   183|---

## Known Limitations (beta)

| Area | Status |
|---|---|
| **Vector search** | Not needed. Personal-scope memory (<10K facts) works fine with BM25. |
| **Multi-user** | Single-user only. No per-user isolation — scope/project is the only partitioning. |
| **Concurrent writes** | File-locked per-write. Not designed for parallel agent swarms writing to the same store. |
| **Migration tooling** | No `import-from` for mem0/Graphiti/LangMem formats yet. JSONL is intentionally simple for manual migration. |
| **API stability** | CLI flags and fact schema may change before v1.0.0. The JSONL format itself is stable and backward-readable. |
| **Embedding providers** | Not planned. See [ARCHITECTURE.md](docs/architecture.md) for the rationale. |

If any of these are blockers for your use case, [open an issue](https://github.com/siar765/agent-memory/issues).

---

## License
   184|
   185|MIT
   186|
   187|