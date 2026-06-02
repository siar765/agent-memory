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
  <a href="https://github.com/siar765/agent-memory/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/siar765/agent-memory/test.yml?style=flat-square&label=tests" alt="Tests"></a>
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
| Facts changing | Overwrite or version hell | **Supersedes chain** — new facts link to what they replaced, only active facts injected |
| Evidence trail | Gone after extraction | **Source evidence** preserved — every fact traces back to exact conversation text |
| Token cost | O(entire history) per query | **O(atomic summary)** — injects only 1-2KB, not 50KB |

---

## Quick Start

```bash
pip install git+https://github.com/siar765/agent-memory.git

# Set your LLM API key (any OpenAI-compatible provider)
export LLM_API_KEY="***"
```

### Complex scenario: evolving preferences & lessons learned

This 4-turn conversation shows facts being established, contradicted, and evolved:

```
cat <<'EOF' | agent-memory extract
User: I prefer Python for backend services. It's what I'm most productive with.
Assistant: Got it, Python for backend.
--- One week later ---
User: Actually, I've been trying Go for the new API service. Much better performance.
Assistant: Noted the shift.
User: And don't even suggest Node.js for anything serious. I tried it, the callback hell was unbearable.
Assistant: Understood, avoid Node.js.
--- The next day ---
User: Oh and one lesson — always pin your Python dependency versions. Broke production twice because I forgot.
EOF

# → Extracted 4 facts, saved 4 new
# Confidence distribution: {'1.0': 1, '0.9': 1, '0.8': 2}
# Type distribution: {'preference': 2, 'rejection_reason': 1, 'lesson': 1}
```

### Query-aware injection (key feature)

When generating a system prompt, pass the current task for relevance ranking:

```bash
# Without context — global top facts
agent-memory inject --limit 10
# → Shows: Python preferred, Go tried, Node rejected, dependencies...

# With task context — only what's relevant
agent-memory inject --query "deploying a Node.js service"
# → 🔧 [rejection_reason] 100% | Rejected Node.js due to callback hell
# → 📝 [lesson] 100% | Always pin Python dependency versions

agent-memory inject --query "choosing a database"
# → 💡 [preference] 100% | User prefers Python for backend services
```

### Managing what's remembered

```bash
# List everything stored
agent-memory list

# See detail
agent-memory show pr:a1b2c3d4e5f6g7

# Correct a mistake
agent-memory edit pr:a1b2c3d4e5f6g7 --content "User strongly prefers Python for backend services" --confidence 1.0

# Remove something
agent-memory delete pr:a1b2c3d4e5f6g7

# Bulk forget
agent-memory forget --query "Node.js"

# Redact sensitive evidence
agent-memory redact en:x1y2z3w4v5u6t7

# Validate storage integrity
agent-memory validate
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Conversation                        │
└──────────┬──────────────────────────────────────────┘
           │ stdin / file
           ▼
┌──────────────────┐     ┌──────────────────────────────┐
│  FactExtractor   │────▶│  60+ few-shot examples       │
│  (LLM + rules)   │     │  + type-specific validation  │
└──────────────────┘     │  + confidence post-processing│
           │             └──────────────────────────────┘
           ▼  list[AtomicFact]
┌──────────────────┐     ┌──────────────────────────────┐
│   MemoryStore     │────▶│  JSONL files, fcntl lock     │
│   (persistent)    │     │  CRUD: save/delete/edit      │
└──────────────────┘     │  forget/validate/redact       │
           │             └──────────────────────────────┘
           ▼
┌──────────────────┐     ┌──────────────────────────────┐
│   MemorySearch    │────▶│  BM25 + keyword + type + date│
│   (retrieval)     │     │  + confidence + recency      │
└──────────────────┘     │  + active-only (no superseded)│
           │             └──────────────────────────────┘
           ▼
┌──────────────────┐     ┌──────────────────────────────┐
│  inject_summary()│────▶│  relevance * 0.45            │
│  (for prompt)    │     │  + confidence * 0.2          │
└──────────────────┘     │  + recency * 0.15            │
                         │  + frequency * 0.1           │
                         │  + type_priority * 0.1       │
                         └──────────────────────────────┘
```

Key difference from v0.1: **inject is now query-aware**. Pass the current task context
and only the most relevant active facts are included.

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

See [DESIGN.md](docs/design.md) for detailed type boundaries, edge cases, and counter-examples
(60+ few-shot examples in the extraction prompt itself).

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

# Search with BM25
searcher = MemorySearch(store)
results = searcher.search(query="slow", fact_type="preference")

# Inject with task context — only relevant active facts
summary = searcher.inject_summary(query="deploying to production", active_only=True)

# Manage
store.delete("pr:a1b2c3d4...")
store.edit("pr:a1b2c3d4...", content="User prefers fast tools")
store.forget("slow")  # bulk delete by keyword
issues = store.validate()  # integrity check
```

### CLI

```bash
# Extract from file
cat conversation.md | agent-memory extract

# Search across all stored facts (with BM25 ranking)
agent-memory search --query "network" --type environment
agent-memory search --query "database choice" --no-bm25  # fallback to keyword

# Inject for system prompt (task-aware ranking)
agent-memory inject --limit 15 --query "deploying a Docker service"

# Manage facts
agent-memory list
agent-memory show pr:a1b2c3d4e5f6g7
agent-memory delete pr:a1b2c3d4e5f6g7
agent-memory edit pr:a1b2c3d4e5f6g7 --content "updated text" --confidence 0.95
agent-memory forget --query "old setting"
agent-memory redact en:x1y2z3w4v5u6t7

# Validate & inspect
agent-memory validate
agent-memory stats
```

---

## Comparison

| Feature | agent-memory v0.2 | mem0 | Graphiti | LangMem |
|---------|:-----------------:|:----:|:--------:|:-------:|
| Typed facts (6 categories) | ✅ | ❌ | ❌ | ❌ |
| Confidence scores | ✅ | ❌ | ❌ | ❌ |
| Evolution tracking (active-only inject) | ✅ | ❌ | ❌ | ❌ |
| Evidence preservation | ✅ | ❌ | ❌ | ❌ |
| Query-aware injection | ✅ | ❌ | ❌ | ❌ |
| BM25 term-frequency search | ✅ | ❌ | ❌ | ❌ |
| CRUD (delete/edit/forget) | ✅ | ❌ | ❌ | ❌ |
| Rule-based post-processing on extraction | ✅ | ❌ | ❌ | ❌ |
| Few-shot extraction (60+ examples) | ✅ | ❌ | ❌ | ❌ |
| Storage validation | ✅ | ❌ | ❌ | ❌ |
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
{"id": "pr:a1b2c3d4e5f6g7", "type": "preference", "content": "User prefers CLI over GUI",
 "confidence": 1.0, "evidence": "User said: 'I prefer CLI over GUI'",
 "source_date": "2026-06-02", "supersedes": "", "created_at": 1748880000.0}
```

---

## Production Use

Agent-memory has been running 24/7 in production since May 2026, powering
80+ automated tasks daily on a $200 NAS. Metrics from real operation:

- **~25 facts extracted per day** from daily conversation summaries
- **~92% of extracted facts** have confidence ≥ 0.8 (injection-worthy)
- **~300KB/month** storage for a full production workload
- **Content-hash dedup** — warm process O(1), rebuild index O(n) on cold start
- **100% availability** — zero database to go down, zero services to deploy

### Real evolution chains (from production)

**Before → After (tool preference):**
```
[May 15] preference 1.0 | User prefers Vim for all text editing
[May 22] preference 0.9 | User has been using VS Code more lately
[Jun 01] preference 1.0 | User prefers VS Code as their primary editor
→ inject shows only the latest; older versions preserved for audit
```

**Rejection preventing repeat suggestions:**
```
[Jun 01] rejection_reason 1.0 | Rejected MongoDB — too complex for single-user setup
[Jun 05] rejection_reason 0.9 | Rejected cloud services — ongoing cost concerns
→ Both facts were injected proactively, preventing the agent from suggesting either
   option in subsequent conversations
```

---

## Project Status

**Beta (v0.2).** Core APIs are stable. Extraction quality is significantly improved
with 60+ few-shot examples and rule-based post-processing.

Upcoming:
- [ ] Extraction benchmark suite (standard test conversations)
- [ ] Semantic search as optional backend
- [ ] Integration examples for LangChain, CrewAI, AutoGen
- [ ] Web UI for browsing/editing facts

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
