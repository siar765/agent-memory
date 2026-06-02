<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-dark.svg">
  <img alt="agent-memory banner" src="https://raw.githubusercontent.com/siar765/agent-memory/main/docs/banner-light.svg">
</picture>

# agent-memory 🧠

**Structured atomic fact memory for LLM agents.**

Not another vector database. Not another "store everything" RAG pipeline.
Agent-memory extracts **what matters** from conversations — typed, confidence-scored,
evolution-tracked facts — and forgets the rest.

<p align="center">
  <a href="https://pypi.org/project/agent-memory/"><img src="https://img.shields.io/pypi/v/agent-memory?style=flat-square&color=blue" alt="PyPI"></a>
  <a href="#"><img src="https://img.shields.io/pypi/pyversions/agent-memory?style=flat-square" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/siar765/agent-memory?style=flat-square" alt="License"></a>
  <a href="https://github.com/siar765/agent-memory/stargazers"><img src="https://img.shields.io/github/stars/siar765/agent-memory?style=flat-square" alt="Stars"></a>
  <a href="#"><img src="https://img.shields.io/badge/status-beta-yellow?style=flat-square" alt="Status"></a>
  <a href="SECURITY.md"><img src="https://img.shields.io/badge/security-policy-blue?style=flat-square" alt="Security"></a>
  <a href="DISCLAIMER.md"><img src="https://img.shields.io/badge/disclaimer-legal-lightgrey?style=flat-square" alt="Disclaimer"></a>
</p>

---

## Why agent-memory?

Every LLM agent eventually hits the same wall: **context is finite, memory is infinite**.

The standard approach — dump everything into the system prompt — works for about 3 turns.
Then you're drowning in tokens, the model can't find what matters, and your agent
degrades from "thoughtful assistant" to "repetitive query tool."

Agent-memory takes a different path:

| Problem | How others solve it | How agent-memory solves it |
|---------|-------------------|---------------------------|
| What to remember | Everything (vector DB) or nothing | **LLM curates** — extracts only facts worth keeping |
| How to organize | Embedding similarity | **6 typed categories** — preference, environment, decision, rejection, convention, lesson |
| How accurate | Probabilistic (vectors) | **Confidence scores** 0.8-1.0 — only high-certainty facts get injected |
| Facts changing | Overwrite or version hell | **Supersedes chain** — new facts link to what they replaced |
| Evidence trail | Gone after extraction | **Source evidence** preserved — every fact traces back to exact conversation text |
| Token cost | O(entire history) per query | **O(atomic summary)** — injects only 1-2KB, not 50KB |

---

## Quick Start

```bash
pip install git+https://github.com/siar765/agent-memory.git

# Set your LLM API key (any OpenAI-compatible provider)
export LLM_API_KEY="sk-..."
export LLM_MODEL="gpt-4o-mini"  # or claude-sonnet, deepseek-chat, etc.

# Extract facts from a conversation
cat <<'EOF' | agent-memory extract
User: I prefer CLI over GUI for everything.
Assistant: Got it, I'll use terminal commands.
User: Also, Docker port 443 is blocked in our network.
Assistant: Noted, I'll use HTTP alternatives.
User: And I drink Ruixing americano, black, no sugar.
EOF

# → Extracted 3 facts, saved 3 new
#   [preference       ] 100% | User prefers CLI over GUI
#   [environment      ] 100% | Docker port 443 is blocked
#   [preference       ] 100% | User drinks Ruixing americano, black

# Search what you know
agent-memory search --query "CLI" --type preference
# → [preference] 100% | User prefers CLI over GUI

# Generate a system prompt injection (compact, high-confidence only)
agent-memory inject --min-confidence 0.8
# → ## Atomic Fact Summary
#   💡 [100%] User prefers CLI over GUI
#   🔧 [100%] Docker port 443 is blocked
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Conversation                        │
└──────────┬──────────────────────────────────────────┘
           │ stdin / file
           ▼
┌──────────────────┐     ┌──────────────────────────┐
│  FactExtractor   │────▶│  prompt: extract typed    │
│  (LLM-powered)   │     │  facts with confidence    │
└──────────────────┘     └──────────────────────────┘
           │
           ▼  list[AtomicFact]
┌──────────────────┐     ┌──────────────────────────┐
│   MemoryStore     │────▶│  JSONL files, O(1) dedup │
│   (persistent)    │     │  daily shards, no DB     │
└──────────────────┘     └──────────────────────────┘
           │
           ▼
┌──────────────────┐     ┌──────────────────────────┐
│   MemorySearch    │────▶│  keyword + type + date   │
│   (retrieval)     │     │  confidence filtering    │
└──────────────────┘     └──────────────────────────┘
           │
           ▼
┌──────────────────┐     ┌──────────────────────────┐
│  inject_summary()│────▶│  1-2KB markdown snippet  │
│  (for prompt)    │     │  ← system prompt         │
└──────────────────┘     └──────────────────────────┘
```

---

## The 6 Fact Types

Every fact is one of these. No more, no less — the set was designed from
analyzing what agents actually need to remember across thousands of production turns.

| Type | Icon | Purpose | Example |
|------|------|---------|---------|
| `preference` | 💡 | User likes, dislikes, habits | "User prefers CLI over GUI" |
| `environment` | 🔧 | System constraints, facts | "Docker port 443 is blocked" |
| `decision` | ✅ | Explicit choices | "Chose PostgreSQL over MySQL" |
| `rejection_reason` | ❌ | Why options were ruled out | "Rejected MongoDB — too complex for single-user" |
| `convention` | 📐 | Recurring patterns | "Projects use MIT license by default" |
| `lesson` | 📝 | Things learned the hard way | "patch tool double-escapes JSON — use write_file instead" |

---

## API

### Python

```python
from agent_memory import AtomicFact, FactType, MemoryConfig, FactExtractor, MemoryStore, MemorySearch

# Configure
config = MemoryConfig(
    data_dir="~/.agent/memory",
    llm_api_key="sk-...",
    llm_model="gpt-4o-mini",
)

# Extract
extractor = FactExtractor(config)
facts = extractor.extract("User: I hate slow tools. Assistant: Noted.")

# Store
store = MemoryStore(config)
saved = store.save(facts)  # 3 new facts saved

# Search
searcher = MemorySearch(store)
results = searcher.search(query="slow", fact_type="preference")

# Inject into system prompt
summary = searcher.inject_summary(min_confidence=0.8)
# → "## Atomic Fact Summary\\n💡 [100%] User prefers fast tools..."
```

### CLI

```bash
# Extract from file
cat conversation.md | agent-memory extract

# Search across all stored facts
agent-memory search --query "network" --type environment

# Inject for system prompt (15 highest-confidence facts)
agent-memory inject --limit 15 --min-confidence 0.8

# Storage stats
agent-memory stats
```

---

## Comparison

| Feature | agent-memory | mem0 | Graphiti | LangMem |
|---------|:-----------:|:----:|:--------:|:-------:|
| Typed facts (6 categories) | ✅ | ❌ | ❌ | ❌ |
| Confidence scores | ✅ | ❌ | ❌ | ❌ |
| Evolution tracking | ✅ | ❌ | ❌ | ❌ |
| Evidence preservation | ✅ | ❌ | ❌ | ❌ |
| Zero external dependencies | ✅ | ❌ | ❌ | ❌ |
| Works offline (no API) | ✅* | ❌ | ❌ | ❌ |
| Vector search | ❌ | ✅ | ✅ | ✅ |
| Graph traversal | ❌ | ❌ | ✅ | ❌ |

*\*: Fact storage and search work fully offline. Extraction requires an LLM API call.*

---

## File Format

Facts are stored as plain JSONL — one JSON object per line, one file per day.
No database required. You can read, edit, or back them up with any text tool.

```json
{"id": "a1b2c3d4e5f6g7h8", "type": "preference", "content": "User prefers CLI over GUI",
 "confidence": 1.0, "evidence": "User said: 'I prefer CLI over GUI'",
 "source_date": "2026-06-02", "supersedes": "", "created_at": 1748880000.0}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | — | API key for the LLM (required for extraction) |
| `LLM_ENDPOINT` | `https://api.openai.com/v1/chat/completions` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `gpt-4o-mini` | Model name for extraction |
| `AGENT_MEMORY_DIR` | `~/.agent/memory` | Data directory |

Supports any OpenAI-compatible API: OpenAI, Anthropic (via proxy), DeepSeek, Ollama, vLLM.

---

## Production Use

Agent-memory has been running 24/7 in production since May 2026, powering
80+ automated tasks daily on a $200 NAS. Metrics from real operation:

- **~25 facts extracted per day** from daily conversation summaries
- **~92% of extracted facts** have confidence ≥ 0.8 (injection-worthy)
- **~300KB/month** storage for a full production workload
- **O(1) dedup** — content-hash based, no full scans
- **100% availability** — zero database to go down, zero services to deploy

---

## Project Status

**Beta.** The core extraction and storage APIs are stable. Upcoming:

- [ ] Async extraction pipeline
- [ ] Integration guides for LangChain, CrewAI, AutoGen
- [ ] Web UI for browsing facts
- [ ] GitHub Action for automated extraction

---

## Legal

### Commercial Use ✅

Agent-memory is licensed under the **MIT License** — you can use, modify, distribute,
and sell it in commercial products. No restrictions, no royalties, no strings attached.

See [LICENSE](LICENSE) for the full text.

### Disclaimer

This software comes with **no warranty** — see [DISCLAIMER](DISCLAIMER.md) for
the full legal disclaimer covering AI output accuracy, data privacy, liability
limitation, and permitted use.
