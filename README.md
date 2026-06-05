<p align="center">
  <img alt="agent-memory" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-light.svg#gh-light-mode-only" width="600">
  <img alt="agent-memory" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-dark.svg#gh-dark-mode-only" width="600">
</p>

<h3 align="center">Your agent shouldn't forget who you are every three weeks</h3>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/siar765/agent-memory?style=flat-square" alt="License"></a>
  <a href="https://github.com/siar765/agent-memory/releases/tag/v1.0.0-beta.6"><img src="https://img.shields.io/badge/status-beta-yellow?style=flat-square" alt="Beta"></a>
  <a href="#zero-dependencies"><img src="https://img.shields.io/badge/dependencies-zero-brightgreen?style=flat-square" alt="Zero dependencies"></a>
  <a href="https://github.com/siar765/agent-memory/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/siar765/agent-memory/test.yml?style=flat-square&label=tests" alt="Tests"></a>
  <a href="https://github.com/siar765/agent-memory/stargazers"><img src="https://img.shields.io/github/stars/siar765/agent-memory?style=flat-square" alt="Stars"></a>
</p>

<p align="center">
  <b>Zero external dependencies · No server · No vector DB · No hidden state</b><br>
  Every memory is a line in a text file you can <code>grep</code>.
</p>

<br>

---

## What it does

**Agent-memory is a local-first, editable memory layer for personal AI agents.** It pulls durable facts out of conversations—your preferences, decisions, rejected options, project context—stores them as typed JSONL entries, and injects only what's relevant into your agent's system prompt. No token bloat. No black-box vector databases.

```bash
pip install git+https://github.com/siar765/agent-memory.git
```

---

## Core features

<table>
<tr>
  <td width="33%"><b>🧠 6 Fact Types</b><br><small>Not just blobs of text. Every memory knows what it is: preference, environment, decision, rejection reason, convention, lesson.</small></td>
  <td width="33%"><b>📝 Editable</b><br><small>Wrong memory? Fix it. <code>edit</code>, <code>delete</code>, <code>redact</code>, <code>forget</code> — you're in control.</small></td>
  <td width="33%"><b>🔗 Evolution Chain</b><br><small>Correct a fact without losing history. Old one stays as superseded, new one links back.</small></td>
</tr>
<tr>
  <td width="33%"><b>📦 Project Isolation</b><br><small>Work memories don't leak into personal context. Plus global merge for preferences.</small></td>
  <td width="33%"><b>✅ Review Gate</b><br><small>Auto-detected patterns land as <code>proposed</code>—kept out of your agent's prompt until you approve.</small></td>
  <td width="33%"><b>📉 Confidence Scoring</b><br><small>0.0–1.0 with configurable half-life decay. Old facts fade, not clutter.</small></td>
</tr>
</table>

**It's just JSONL.** Every memory is one line in a text file. Grep it, `jq` it, back it up with `rsync`, version it with git. Zero binary blobs, zero database dumps, zero vendor lock-in.

---

## How it works

```
Conversation  →  [LLM Extractor]  →  [JSONL Storage]  →  [BM25 Search]  →  System Prompt
                                                          ↕
                                                  grep/jq/git/rsync
```

- **No vector DB** — personal memory (<10K facts) works fine with pure-Python BM25
- **No dependencies** — Python stdlib only. Install anywhere.
- **Atomic writes** — file lock + `os.replace()`, zero corruption risk
- **~1-2 KB injection** — not 50 KB of irrelevant context

---

## Real-world numbers

Running 24/7 since May 2026, powering 80+ automated daily tasks on a NAS:

| Metric | Value |
|---|---|
| Facts extracted per day | ~25 |
| Inject size | ~1-2 KB (15 active facts) |
| Extraction time | ~1.5s per conversation |
| External deps | **Zero** |

---

## Quick start

```bash
# 1. Install
pip install git+https://github.com/siar765/agent-memory.git
export LLM_API_KEY="sk-..."    # any OpenAI-compatible provider

# 2. Extract memories
echo "User: We use PostgreSQL for this project." | agent-memory extract

# 3. Search & inject
agent-memory search --query "editor preference"
agent-memory inject --project blog --limit 10
```

That's it. No server to start, no database to configure, no API to sign up for.

---

## Compared to alternatives

| | agent-memory | mem0 | Graphiti | LangMem | Hy-Memory |
|---|---|---|---|---|---|
| **Dependencies** | **Zero** | Chroma/Pinecone + embedding API | Neo4j + infra | Entire LangChain stack | OpenClaw framework |
| **Install** | `pip install` | sign up + API key + DB | docker-compose | pip + 12 deps | framework plugin |
| **Local-first** | ✅ | ❌ cloud API | ❌ graph server | ✅ | ✅ |
| **Editable facts** | ✅ edit/delete/redact | ❌ read-only | ⚠️ manual | ⚠️ manual | ❌ |
| **Evolution chain** | ✅ supersedes+history | ❌ | ✅ | ❌ | ✅ |
| **Review gate** | ✅ propose→accept/reject | ❌ | ❌ | ❌ | ❌ |
| **Confidence scoring** | ✅ 0.0-1.0 + decay | ❌ | ❌ | ❌ | ❌ |
| **File format** | JSONL — grep/jq/git | proprietary | graph DB | proprietary | proprietary |

---

## Known limitations (beta)

| Area | Status |
|---|---|
| **Vector search** | Not needed for <10K facts. BM25 handles it. |
| **Multi-user** | Single-user only. scope/project is the only partitioning. |
| **Concurrent writes** | File-locked per write. Not for parallel swarms. |
| **API stability** | CLI flags may change before v1.0.0. JSONL format is stable. |

---

## ‍♂️ The backstory

Every agent memory system promises "remember forever." Here's what they don't tell you — they need a vector database, an embedding API, a cloud service, a graph server, or half the LangChain ecosystem installed on your machine.

**That's insane for one person running an agent on their laptop.**

Agent-memory is the opposite: zero deps, local file storage, no servers, no sign-ups. It solves *your* memory — the person who just wants their agent to remember what they said last week without spinning up infrastructure.

---

## License

MIT
