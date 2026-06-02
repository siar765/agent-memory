     1|
     2|<p align="center">
     3|  <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-light.svg#gh-light-mode-only">
     4|  <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-dark.svg#gh-dark-mode-only">
     5|</p>
     6|
     7|<h3 align="center">Your agent shouldn't forget who you are every three weeks</h3>
     8|
     9|<p align="center">
    10|  <a href="LICENSE"><img src="https://img.shields.io/github/license/siar765/agent-memory?style=flat-square" alt="License"></a>
    11|  <a href="https://github.com/siar765/agent-memory/releases/tag/v1.0.0-beta.6"><img src="https://img.shields.io/badge/status-beta-yellow?style=flat-square" alt="Beta"></a>
    12|  <a href="#zero-dependencies"><img src="https://img.shields.io/badge/dependencies-zero-brightgreen?style=flat-square" alt="Zero dependencies"></a>
    13|  <a href="https://github.com/siar765/agent-memory/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/siar765/agent-memory/test.yml?style=flat-square&label=tests" alt="Tests"></a>
    14|  <a href="https://github.com/siar765/agent-memory/stargazers"><img src="https://img.shields.io/github/stars/siar765/agent-memory?style=flat-square" alt="Stars"></a>
    15|  <a href="DISCLAIMER.md"><img src="https://img.shields.io/badge/disclaimer-legal-lightgrey?style=flat-square" alt="Disclaimer"></a>
    16|</p>
    17|
    18|**Zero external dependencies. No server. No vector DB. No hidden state.**
    19|Every memory is a line in a text file you can grep.
    20|
    21|---
    22|
    23|## The problem
    24|
    25|Every agent memory system promises the same thing — "remember forever." Here's what they don't tell you:
    26|
    27|| | agent-memory | mem0 | Graphiti | LangMem | Hy-Memory |
    28||---|---|---|---|---|---|
    29|| **Dependencies** | **Zero** | Chroma/Pinecone + embedding API | Neo4j + infra | Entire LangChain stack | OpenClaw framework |
    30|| **Install** | `pip install` | sign up + API key + DB setup | docker-compose | pip + 12 deps | framework plugin |
    31|| **Local-first** | ✅ | ❌ (cloud API) | ❌ (graph server) | ✅ | ✅ |
    32|| **Editable facts** | ✅ (edit/delete/redact/forget) | ❌ (read-only) | ⚠️ (manual) | ⚠️ (manual) | ❌ |
    33|| **Evolution chain** | ✅ (supersedes with history) | ❌ | ✅ | ❌ | ✅ |
    34|| **Review gate** | ✅ (propose→review→accept/reject) | ❌ | ❌ | ❌ | ❌ |
    35|| **Project isolation** | ✅ (+ global merge, no leaks) | ❌ | ❌ | ❌ | ✅ |
    36|| **File format** | JSONL — grep/jq/git | proprietary | graph DB | proprietary | proprietary |
    37|| **Single-user targeted** | ✅ | ❌ (multi-user SaaS) | ❌ (enterprise) | ❌ (framework) | ✅ |
    38|| **Confidence scoring** | ✅ (0.0-1.0) | ❌ | ❌ | ❌ | ❌ |
    39|| **Secret redaction** | ✅ (redact command) | ❌ | ❌ | ❌ | ❌ |
|| **Run offline** | ✅ storage/search/inject · ❌ extract needs LLM API | ❌ | ❌ | ✅ | ✅ |
    41|
    42|**The others solve "enterprise multi-user memory."** agent-memory solves *your* memory — the person running an agent on their laptop, who just wants their agent to remember what they said last week without spinning up a vector database.
    43|
    44|---
    45|
    46|## Enter agent-memory
    47|
    48|```bash
    49|pip install git+https://github.com/siar765/agent-memory.git
    50|# No server. No database. No external API for search.
    51|# Extraction requires an LLM API key (see Quick start).
    52|```
    53|
    54|Agent-memory is a **local-first, editable memory layer for personal AI agents.** It extracts durable facts from conversations — what you like, what you decided, what doesn't work — stores them as typed, confidence-scored entries in plain JSONL, and injects only relevant ones into your agent's system prompt. Your agent remembers you, session after session, without token bloat or black-box vector databases.
    55|
    56|```bash
    57|# Extract facts from a conversation
    58|echo "User: I use VS Code for Python, Neovim for everything else" | \
    59|  agent-memory extract
    60|
    61|# Search what the agent remembers
    62|agent-memory search --query "editor preference"
    63|
    64|# Inject relevant memories into your agent's system prompt
    65|agent-memory inject --query "project context"
    66|```
    67|
    68|**Output:**
    69|```
    70|$ agent-memory list
    71| pr:4a1b2c3d    preference   active   "Prefers CLI over GUI for system tasks"
    72| en:5e6f7a8b    environment  active   "Docker 443 blocked, no git clone over HTTPS"
    73| dc:9c0d1e2f    decision     active   "Using PostgreSQL for blog project"
    74| re:3a4b5c6d    rejection    active   "Ruled out MongoDB — too heavy for NAS"
    75| co:7e8f9a0b    convention   active   "Chinese for design docs, English for code"
    76| le:1c2d3e4f    lesson       active   "Don't run apt upgrade before cron jobs"
    77|```
    78|
    79|---
    80|
    81|## What makes it different
    82|
    83|**It's just JSONL** — every memory is one line in a text file. You can `grep` it, `jq` it, back it up with `rsync`, version it with git. No binary blobs, no database dumps, no vendor lock-in.
    84|
    85|**6 fact types** — not a blob of text. Every memory knows what it is:
    86|
    87|| Type | What it captures |
    88||---|---|
    89|| `preference` 💡 | User likes, dislikes, habits |
    90|| `environment` 🔧 | System constraints, network limits |
    91|| `decision` ✅ | Explicit choices with rationale |
    92|| `rejection_reason` ❌ | What was ruled out and why |
    93|| `convention` 📐 | Recurring patterns, practices |
    94|| `lesson` 📝 | Mistakes, corrections, insights |
    95|
    96|**Editable** — wrong memory? Fix it:
    97|
    98|```bash
    99|agent-memory edit pr:4a1b2c3d --content "User prefers VS Code now"
   100|agent-memory delete pr:old_obsolete_fact
   101|agent-memory redact pr:sensitive_fact  # mask evidence, keep the fact
   102|agent-memory forget --query "old information i no longer need"
   103|```
   104|
   105|**Project-scoped** — work memories don't leak into your personal context:
   106|
   107|```bash
   108|agent-memory extract --scope project --project blog
   109|agent-memory inject --scope project --project blog --include-global
   110|# --include-global merges global preferences with project-specific facts
   111|```
   112|
   113|**Evolution chain** — correct a fact without losing history. The old fact is preserved as `superseded`, the new one links back:
   114|
   115|```
   116|[Old] "Prefers dark mode"  ──supersedes──→ [New] "Now prefers light mode"
   117|    status=superseded                           status=active
   118|                                ↕
   119|              inject/search default to active, exclude superseded/proposed
   120|```
   121|
   122|**Review gate** — auto-detected patterns land as `proposed` facts, kept out of your agent's prompt until you review:
   123|
   124|```bash
   125|agent-memory propose "User checks crypto prices daily" --type convention
   126|agent-memory list --status proposed   # review pending proposals
   127|agent-memory accept pr:xxx --confidence 0.9  # promote to active
   128|agent-memory reject pr:xxx           # discard
   129|```
   130|
   131|---
   132|
   133|## Real-world numbers
   134|
   135|Been running 24/7 since May 2026, powering 80+ automated daily tasks on a NAS:
   136|
   137|| Metric | Value |
   138||---|---|
   139|| Facts extracted per day | ~25 |
   140|| Inject size for system prompt | ~1-2 KB (15 active facts) |
   141|| Extraction time per conversation | ~1.5s (gpt-4o-mini) |
   142|| Storage method | JSONL, grep-able |
   143|| External dependencies | **Zero** |
   144|| Dedup after startup | O(1) |
   145|
   146|---
   147|
   148|## Architecture in 30 seconds
   149|
   150|```
   151|Conversation text
   152|       ↓
   153|  [LLM extractor]  ← typed, scoped, confidence-scored
   154|       ↓
   155|  [JSONL storage]  ← one file per day, grep-able, git-versionable
   156|       ↓
   157|  [BM25 search]    ← zero-dependency ranking, CJK support
   158|       ↓
   159|  [Inject summary] → system prompt (1-2 KB, not 50 KB)
   160|```
   161|
   162|Key design decisions:
   163|- **No vector DB** — personal-scope memory (<10K facts) doesn't need it
   164|- **No dependencies** — pure Python stdlib. Install anywhere.
   165|- **No hidden state** — every fact is visible, editable, deletable
   166|- **Atomic writes** — file lock + `os.replace()`, no corruption
   167|
   168|---
   169|
   170|## Quick start
   171|
   172|```bash
   173|# 1. Install
   174|pip install git+https://github.com/siar765/agent-memory.git
   175|export LLM_API_KEY="***"  # any OpenAI-compatible provider
   176|export LLM_MODEL="gpt-4o-mini"
   177|
   178|# 2. Extract memories from a conversation
   179|echo "User: We use PostgreSQL for this project." | agent-memory extract
   180|echo "User: I prefer CLI over GUI for everything." | agent-memory extract --scope global
   181|
   182|# 3. Search what's stored
   183|agent-memory search "prefer editor"
   184|agent-memory list --type preference
   185|
   186|# 4. Generate injection summary for your agent's system prompt
   187|agent-memory inject --scope project --project blog --limit 10
   188|
   189|# 5. Fix mistakes
   190|agent-memory edit pr:4a1b2c3d --content "Updated preference"
   191|agent-memory delete pr:obsolete_entry
   192|```
   193|
   194|---
   195|
   196|## Known Limitations (beta)
   197|
   198|| Area | Status |
   199||---|---|
   200|| **Vector search** | Not needed. Personal-scope memory (<10K facts) works fine with BM25. |
   201|| **Multi-user** | Single-user only. No per-user isolation — scope/project is the only partitioning. |
   202|| **Concurrent writes** | File-locked per-write. Not designed for parallel agent swarms writing to the same store. |
   203|| **Migration tooling** | No `import-from` for mem0/Graphiti/LangMem formats yet. JSONL is intentionally simple for manual migration. |
   204|| **API stability** | CLI flags and fact schema may change before v1.0.0. The JSONL format itself is stable and backward-readable. |
   205|
   206|If these are blockers, [open an issue](https://github.com/siar765/agent-memory/issues).
   207|
   208|---
   209|
   210|## License
   211|
   212|MIT
   213|