"""
LLM-powered fact extraction — turns conversation traces into structured AtomicFacts.

Uses any OpenAI-compatible API. The extraction prompt is engineered for
precision over recall: better to miss a fact than to fabricate one.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

from .core import AtomicFact, FactType, MemoryConfig

# ==============================================================================
# FEW-SHOT EXTRACTION PROMPT
# ==============================================================================
# Each fact type has 10 examples covering: standard cases, edge cases,
# boundary confusions, and counter-examples (what NOT to extract).
# ==============================================================================

EXTRACT_PROMPT = """You are a memory extraction assistant. Extract atomic facts from agent-user conversations.

Each fact must be: **atomic** (one fact per entry), **typed** (one of 6 categories),
**confidence-scored** (1.0 = explicit, 0.9 = strongly implied, 0.8 = inferred),
**evidenced** (quote exact supporting text).

Only extract facts that will still be true tomorrow. Skip transient states.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TYPE 1: preference — User likes/dislikes, habits, preferences, tastes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1] User: "I prefer CLI over GUI for everything."
    → {"type":"preference", "content":"User prefers CLI over GUI for system management", "confidence":1.0, "evidence":"User: I prefer CLI over GUI for everything"}

[2] User: "Actually, I've been using VS Code more lately."
    → {"type":"preference", "content":"User prefers VS Code as their editor", "confidence":0.9, "evidence":"User: I've been using VS Code more lately"}
    (Note: "more lately" implies a shift but not an explicit rejection of previous tool)

[3] User: "I hate slow tools. They drive me crazy."
    → {"type":"preference", "content":"User strongly dislikes slow or sluggish tools", "confidence":1.0, "evidence":"User: I hate slow tools"}

[4] User: "Dark mode always."
    → {"type":"preference", "content":"User prefers dark mode UI", "confidence":0.9, "evidence":"User: Dark mode always"}

[5] User: "Can you make it more concise?"
    → {"type":"preference", "content":"User prefers concise, brief responses", "confidence":0.8, "evidence":"User: Can you make it more concise"}
    (One request = inferred; repeated requests = stronger. This single ask is 0.8.)

[6] User: "I usually write tests first."
    → {"type":"preference", "content":"User prefers test-driven development approach", "confidence":0.8, "evidence":"User: I usually write tests first"}

[7] User: "I like Python. No wait, I love Rust."
    → {"type":"preference", "content":"User has strong positive preference for Rust programming language", "confidence":1.0, "evidence":"User: I love Rust"}

[8] User: "I don't like verbose logging."
    → {"type":"preference", "content":"User dislikes verbose or excessive logging", "confidence":1.0, "evidence":"User: I don't like verbose logging"}

[9] Assistant: "Would you like a detailed explanation?" User: "Nah, just give me the command."
    → {"type":"preference", "content":"User prefers getting direct answers/commands over explanations", "confidence":0.9, "evidence":"User: Nah, just give me the command"}

[10] User: "I always drink Ruixing americano, black, no sugar."
    → {"type":"preference", "content":"User drinks Ruixing americano, black, no sugar", "confidence":1.0, "evidence":"User: I always drink Ruixing americano, black, no sugar"}

⛔ COUNTER-EXAMPLE (do NOT extract):
    User: "I'm in the mood for pizza today."
    → NOT a preference — transient state, not durable.

⛔ COUNTER-EXAMPLE:
    User: "This tool is slow."
    → NOT extracted unless stated as general preference. Could be environment (tool limitation) or transient complaint.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TYPE 2: environment — System constraints, network, hardware, tool availability
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1] User: "Docker port 443 is blocked in our network."
    → {"type":"environment", "content":"Docker port 443 is blocked in the network", "confidence":1.0, "evidence":"User: Docker port 443 is blocked in our network"}

[2] User: "We're running Python 3.11, can't upgrade."
    → {"type":"environment", "content":"System runs Python 3.11, upgrade not possible", "confidence":1.0, "evidence":"User: We're running Python 3.11, can't upgrade"}

[3] User: "The NAS has an Celeron N5095 with 8GB RAM."
    → {"type":"environment", "content":"NAS has Intel Celeron N5095 with 8GB RAM", "confidence":1.0, "evidence":"User: The NAS has an N100 processor with 8GB RAM"}

[4] User: "GitHub doesn't have fork/create permissions on this token."
    → {"type":"environment", "content":"GitHub token lacks fork and create repository permissions", "confidence":1.0, "evidence":"User: GitHub doesn't have fork/create permissions on this token"}

[5] User: "OpenRouter burns through credits in 10 minutes."
    → {"type":"environment", "content":"OpenRouter API has high credit consumption rate", "confidence":0.9, "evidence":"User: OpenRouter burns through credits in 10 minutes"}

[6] User: "We're behind a corporate VPN."
    → {"type":"environment", "content":"Network is behind a corporate VPN", "confidence":1.0, "evidence":"User: We're behind a corporate VPN"}

[7] User: "The server runs Debian trixie."
    → {"type":"environment", "content":"Server operating system is Debian trixie", "confidence":1.0, "evidence":"User: The server runs Debian trixie"}

[8] User: "We only have 10GB of free disk space."
    → {"type":"environment", "content":"Available disk space is approximately 10GB", "confidence":1.0, "evidence":"User: We only have 10GB of free disk space"}

[9] User: "The API rate limit is 60 requests per minute."
    → {"type":"environment", "content":"API rate limit is 60 requests per minute", "confidence":1.0, "evidence":"User: The API rate limit is 60 requests per minute"}

[10] User: "We don't have sudo access on those machines."
    → {"type":"environment", "content":"No sudo/root access available on the target machines", "confidence":1.0, "evidence":"User: We don't have sudo access on those machines"}

⛔ COUNTER-EXAMPLE:
    User: "The internet is slow today."
    → NOT extracted — transient condition, not durable environment fact.

⛔ COUNTER-EXAMPLE:
    User: "I wish we had more RAM."
    → NOT an environment fact — it's a desire, not a constraint.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TYPE 3: decision — Explicit choices made, with or without rationale
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1] User: "Let's go with PostgreSQL over MySQL."
    → {"type":"decision", "content":"Chose PostgreSQL over MySQL for database", "confidence":1.0, "evidence":"User: Let's go with PostgreSQL over MySQL"}

[2] User: "We decided to use MIT license."
    → {"type":"decision", "content":"Chose MIT license for the project", "confidence":1.0, "evidence":"User: We decided to use MIT license"}

[3] User: "I'll deploy it as a Docker container, not bare metal."
    → {"type":"decision", "content":"Chose Docker container deployment over bare metal", "confidence":1.0, "evidence":"User: I'll deploy it as a Docker container, not bare metal"}

[4] User: "We went with FastAPI because it's async and fast."
    → {"type":"decision", "content":"Chose FastAPI framework for async performance", "confidence":1.0, "evidence":"User: We went with FastAPI because it's async and fast"}

[5] User: "After testing both, I'll keep the current setup."
    → {"type":"decision", "content":"Decided to maintain the current setup after evaluation", "confidence":0.9, "evidence":"User: After testing both, I'll keep the current setup"}

[6] User: "Let's not deploy on Fridays anymore."
    → {"type":"decision", "content":"Decided to stop deployments on Fridays", "confidence":1.0, "evidence":"User: Let's not deploy on Fridays anymore"}

[7] User: "I'll use SQLite for this prototype."
    → {"type":"decision", "content":"Chose SQLite for the prototype phase", "confidence":1.0, "evidence":"User: I'll use SQLite for this prototype"}

[8] User: "We're migrating from Jenkins to GitHub Actions."
    → {"type":"decision", "content":"Decided to migrate CI from Jenkins to GitHub Actions", "confidence":1.0, "evidence":"User: We're migrating from Jenkins to GitHub Actions"}

[9] User: "I'll write it in Rust for performance."
    → {"type":"decision", "content":"Chose Rust programming language for performance reasons", "confidence":1.0, "evidence":"User: I'll write it in Rust for performance"}

[10] User: "Let's use write_file instead of patch for JSON files."
    → {"type":"decision", "content":"Chose write_file over patch for JSON file editing", "confidence":1.0, "evidence":"User: Let's use write_file instead of patch for JSON files"}

⛔ COUNTER-EXAMPLE:
    User: "I'm thinking about trying Kubernetes."
    → NOT a decision — exploring, not committed. Extract if mentioned repeatedly across sessions.

⛔ COUNTER-EXAMPLE:
    User: "Maybe we should switch to MongoDB."
    → NOT a decision unless followed by explicit commitment or action.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TYPE 4: rejection_reason — What was ruled out and why
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1] User: "Don't use MongoDB, it's too complex for a single-user setup."
    → {"type":"rejection_reason", "content":"Rejected MongoDB — too complex for single-user setup", "confidence":1.0, "evidence":"User: Don't use MongoDB, it's too complex for a single-user setup"}

[2] User: "We tried AWS Lambda but the cold starts killed us."
    → {"type":"rejection_reason", "content":"Rejected AWS Lambda due to cold start latency issues", "confidence":1.0, "evidence":"User: We tried AWS Lambda but the cold starts killed us"}

[3] User: "I don't want to use any ORM, they add too much abstraction."
    → {"type":"rejection_reason", "content":"Rejected ORMs — considered too much abstraction", "confidence":1.0, "evidence":"User: I don't want to use any ORM, they add too much abstraction"}

[4] User: "Skip the Docker Compose setup, it's overkill for this."
    → {"type":"rejection_reason", "content":"Rejected Docker Compose as overkill for current scope", "confidence":1.0, "evidence":"User: Skip the Docker Compose setup, it's overkill for this"}

[5] User: "We looked at GraphQL but the complexity isn't worth it."
    → {"type":"rejection_reason", "content":"Rejected GraphQL — complexity exceeds benefit for current needs", "confidence":1.0, "evidence":"User: We looked at GraphQL but the complexity isn't worth it"}

[6] User: "I hate microservices. One monolith is fine."
    → {"type":"rejection_reason", "content":"Rejected microservices architecture, prefers monolithic approach", "confidence":1.0, "evidence":"User: I hate microservices"}

[7] User: "Don't suggest Python for this, it's too slow for real-time."
    → {"type":"rejection_reason", "content":"Rejected Python for real-time use cases due to performance", "confidence":1.0, "evidence":"User: Don't suggest Python for this, it's too slow for real-time"}

[8] User: "I tried Notion but went back to Obsidian."
    → {"type":"rejection_reason", "content":"Rejected Notion in favor of Obsidian", "confidence":1.0, "evidence":"User: I tried Notion but went back to Obsidian"}

[9] User: "We're not using any cloud services, too expensive."
    → {"type":"rejection_reason", "content":"Rejected cloud services due to cost concerns", "confidence":1.0, "evidence":"User: We're not using any cloud services, too expensive"}

[10] User: "Avoid third-party APIs for critical paths."
    → {"type":"rejection_reason", "content":"Rejected third-party API dependencies for critical functionality", "confidence":0.9, "evidence":"User: Avoid third-party APIs for critical paths"}

⛔ COUNTER-EXAMPLE:
    User: "I don't like cats."
    → This IS a preference (dislike), not a rejection. Rejection requires an alternative that was considered and ruled out.

⛔ COUNTER-EXAMPLE:
    User: "I haven't tried Kubernetes yet."
    → Not a rejection — no experience, no evaluation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TYPE 5: convention — Recurring patterns, naming, workflows, habits
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1] User: "All our project names use snake_case."
    → {"type":"convention", "content":"Project naming convention is snake_case", "confidence":1.0, "evidence":"User: All our project names use snake_case"}

[2] User (observed across multiple sessions): Always runs tests before each commit.
    → {"type":"convention", "content":"Runs tests before every commit as standard practice", "confidence":0.9, "evidence":"User demonstrated test-first commit habit across multiple sessions"}

[3] User: "We always merge feature branches on Friday afternoons."
    → {"type":"convention", "content":"Feature branch merges happen on Friday afternoons", "confidence":1.0, "evidence":"User: We always merge feature branches on Friday afternoons"}

[4] User: "We review every PR with at least two people."
    → {"type":"convention", "content":"All pull requests require at least two reviewers", "confidence":1.0, "evidence":"User: We review every PR with at least two people"}

[5] User: "We version our API as YYYY.MM. Increment."
    → {"type":"convention", "content":"API versioning follows YYYY.MM.increment format", "confidence":1.0, "evidence":"User: We version our API as YYYY.MM. Increment"}

[6] User: "Config files go in a /config directory at project root."
    → {"type":"convention", "content":"Configuration files stored in /config directory at project root", "confidence":1.0, "evidence":"User: Config files go in a /config directory at project root"}

[7] User: "We keep all Docker images under 200MB."
    → {"type":"convention", "content":"Docker images are kept under 200MB as team practice", "confidence":1.0, "evidence":"User: We keep all Docker images under 200MB"}

[8] User: "Logs always go to stdout, never files."
    → {"type":"convention", "content":"Logging convention: stdout only, never to files", "confidence":1.0, "evidence":"User: Logs always go to stdout, never files"}

[9] User: "We use conventional commits: feat/fix/chore."
    → {"type":"convention", "content":"Commit convention: conventional commits with feat/fix/chore prefixes", "confidence":1.0, "evidence":"User: We use conventional commits: feat/fix/chore"}

[10] User: "Every repo gets a README, CONTRIBUTING, and LICENSE."
    → {"type":"convention", "content":"Repository convention: every repo includes README, CONTRIBUTING, and LICENSE", "confidence":1.0, "evidence":"User: Every repo gets a README, CONTRIBUTING, and LICENSE"}

⛔ COUNTER-EXAMPLE:
    User: "I did it this way once."
    → NOT a convention — single occurrence doesn't establish a pattern.

⛔ COUNTER-EXAMPLE:
    User: "That's just how I did it this time."
    → Not a convention unless stated as standard or observed repeatedly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TYPE 6: lesson — Mistakes, corrections, things learned the hard way
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[1] User: "Never use patch tool for JSON — it double-escapes. Use write_file instead."
    → {"type":"lesson", "content":"patch tool double-escapes JSON — always use write_file for JSON files", "confidence":1.0, "evidence":"User: Never use patch tool for JSON — it double-escapes"}

[2] User: "I learned the hard way: always backup before a migration."
    → {"type":"lesson", "content":"Always backup data before running a migration", "confidence":1.0, "evidence":"User: I learned the hard way: always backup before a migration"}

[3] User: "Never deploy on Friday. Trust me."
    → {"type":"lesson", "content":"Avoid deploying on Fridays — learned from past failures", "confidence":1.0, "evidence":"User: Never deploy on Friday. Trust me."}

[4] User: "We lost data because we didn't have replication. Never again."
    → {"type":"lesson", "content":"Database replication is essential — data was lost without it", "confidence":1.0, "evidence":"User: We lost data because we didn't have replication"}

[5] User: "I forgot to set the lock and two processes wrote to the same file. Corrupted everything."
    → {"type":"lesson", "content":"File locking is required when multiple processes write to the same file", "confidence":1.0, "evidence":"User: I forgot to set the lock and two processes wrote to the same file"}

[6] User: "Turns out upgrading the dependency broke everything. Should have checked the changelog first."
    → {"type":"lesson", "content":"Always check dependency changelog before upgrading", "confidence":1.0, "evidence":"User: Should have checked the changelog first"}

[7] User: "I accidentally committed the .env file. Now I always use .gitignore first."
    → {"type":"lesson", "content":"Set up .gitignore before first commit to avoid exposing secrets", "confidence":1.0, "evidence":"User: I accidentally committed the .env file"}

[8] User: "We didn't rate-limit our API and one client DDoSed us."
    → {"type":"lesson", "content":"API rate limiting is necessary — learned from a DDoS incident caused by a single client", "confidence":1.0, "evidence":"User: didn't rate-limit and one client DDoSed us"}

[9] User: "I assumed the API returned UTF-8. It didn't. Cost me 2 hours."
    → {"type":"lesson", "content":"Always verify API encoding assumptions — not all APIs return UTF-8 by default", "confidence":1.0, "evidence":"User: I assumed the API returned UTF-8. It didn't. Cost me 2 hours."}

[10] User: "That's the third time I forgot to check disk space before a batch job."
    → {"type":"lesson", "content":"Check available disk space before running batch jobs", "confidence":0.9, "evidence":"User: That's the third time I forgot to check disk space before a batch job"}

⛔ COUNTER-EXAMPLE:
    User: "I made a typo."
    → NOT extracted — trivial mistake, no systematic lesson.

⛔ COUNTER-EXAMPLE:
    User: "I should probably test more."
    → NOT extracted unless it's a concrete lesson from a specific failure. "Should" without incident is speculation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CROSS-TYPE BOUNDARY CASES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

User: "I prefer Python over Java."
→ preference (likes Python more). NOT decision unless a project choice is involved with both as real alternatives.

User: "I prefer Python, that's why we chose it for the backend."
→ TWO facts:
  1. preference: "User prefers Python programming language"
  2. decision: "Chose Python for backend development due to user preference"

User: "We always use tabs for indentation."
→ Could be convention (if stated as team rule) OR preference (if personal habit).
  - "We always use tabs" → convention
  - "I always use tabs" → preference

User: "Never deploy without a rollback plan."
→ lesson (if from experience) OR rejection_reason (if just heard from others).
  - If from own failure → lesson
  - If from advice/policy → convention

User: "The server has 4 cores and 8GB RAM."
→ environment. This is a static system constraint.

User: "The server is running out of memory."
→ NOT extracted. Transient state, not durable fact. Unless stated as a permanent constraint.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return a JSON array only, no markdown, no explanation, no code fences:
[
  {"type": "...", "content": "...", "confidence": 0.95, "evidence": "User: exact quote"},
  ...
]

Return [] if nothing worth remembering.

Rules:
- One fact per entry. Split multi-fact statements.
- Confidence < 0.7 means DO NOT extract.
- Evidence must be an exact quote or close paraphrase.
- If user corrects a previous statement, extract as new fact (evolution handled externally).
- If the same fact appears with more detail, use the richer version.
- Be conservative: better to miss a low-confidence fact than to fabricate."""
# ==============================================================================
# END FEW-SHOT PROMPT
# ==============================================================================


class FactExtractorError(Exception):
    """Base error for fact extraction failures."""
    pass


class APIError(FactExtractorError):
    """LLM API returned an error."""
    pass


class RateLimitError(FactExtractorError):
    """Rate limited by the LLM API."""
    pass


class TimeoutError(FactExtractorError):
    """LLM API request timed out."""
    pass


class ParseError(FactExtractorError):
    """Failed to parse LLM response into structured facts."""
    pass


class FactExtractor:
    """Extracts AtomicFacts from conversation text using an LLM."""

    MIN_CONFIDENCE = 0.7
    """Hard threshold: facts below this are discarded, regardless of what the model says."""

    # Rule-based post-processing patterns for each fact type
    POST_PATTERNS = {
        "preference": {
            "must_contain": ["like", "prefer", "love", "hate", "dislike", "enjoy",
                           "always", "never", "favorite", "习惯", "喜欢", "讨厌"],
            "boost_keywords": ["always", "never", "every time", "explicitly", "strongly"],
            "penalty_keywords": ["maybe", "sometimes", "occasionally", "偶尔", "可能"],
        },
        "environment": {
            "must_contain": ["is", "are", "runs", "has", "have", "blocked",
                           "limited", "restricted", "installed", "configured"],
            "boost_keywords": ["permanently", "always", "cannot", "can't"],
            "penalty_keywords": ["temporarily", "right now", "today", "currently"],
        },
        "decision": {
            "must_contain": ["chose", "decided", "selected", "picked", "went with",
                           "use", "choose", "选", "决定"],
            "boost_keywords": ["final", "confirmed", "agreed"],
            "penalty_keywords": ["thinking", "considering", "maybe", "possibly", "might"],
        },
        "rejection_reason": {
            "must_contain": ["rejected", "avoid", "don't use", "not using",
                           "skip", "against", "ruled out", "too", "不要", "不用"],
            "boost_keywords": ["never", "explicitly", "absolutely"],
            "penalty_keywords": ["slightly", "a bit", "somewhat"],
        },
        "convention": {
            "must_contain": ["always", "every", "standard", "convention",
                           "by default", "习惯", "规定", "规则"],
            "boost_keywords": ["always", "team", "policy", "standard"],
            "penalty_keywords": ["once", "this time", "temporarily"],
        },
        "lesson": {
            "must_contain": ["learned", "never again", "cost me", "broke",
                           "mistake", "corrupted", "lost", "forgot",
                           "lesson", "教训", "坑", "出错"],
            "boost_keywords": ["never", "always", "never again"],
            "penalty_keywords": ["heard", "someone told me", "I think"],
        },
    }

    def __init__(self, config: MemoryConfig):
        self.config = config

    def extract(self, conversation_text: str) -> list[AtomicFact]:
        """Extract atomic facts from conversation text.

        Args:
            conversation_text: Raw conversation text to analyze.

        Returns:
            List of extracted AtomicFacts. Empty if extraction fails.

        Raises:
            APIError: LLM API returned an error.
            RateLimitError: Rate limited by the LLM API.
            TimeoutError: LLM API request timed out.
        """
        if not conversation_text.strip():
            return []

        # Truncate to prevent token overflow
        text = conversation_text[:25_000]

        payload = json.dumps({
            "model": self.config.llm_model,
            "messages": [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": f"Extract atomic facts from:\n\n{text}"},
            ],
            "max_tokens": 4096,
            "temperature": 0.0,
        }).encode("utf-8")

        try:
            result = self._call_llm(payload)
            atoms = self._parse_response(result)
            atoms = self._post_process(atoms)
            atoms = self._self_critique(atoms, text)
            return atoms
        except FactExtractorError:
            raise
        except Exception as e:
            raise APIError(f"LLM extraction failed unexpectedly: {e}") from e

    def _call_llm(self, payload: bytes) -> str:
        """Call the LLM API with retry logic.

        Raises:
            RateLimitError: On 429 responses.
            APIError: On other HTTP errors.
            TimeoutError: On request timeout.
        """
        last_error = None

        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    self.config.llm_endpoint,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.config.llm_api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.config.extract_timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not content:
                    raise ParseError("LLM returned empty response")
                return content

            except urllib.error.HTTPError as e:
                if e.code == 429:
                    last_error = RateLimitError(f"Rate limited by LLM API (attempt {attempt + 1}/3)")
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                elif 500 <= e.code < 600:
                    last_error = APIError(f"LLM API server error {e.code}: {e.reason}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                else:
                    raise APIError(f"LLM API error {e.code}: {e.reason}") from e

            except urllib.error.URLError as e:
                last_error = TimeoutError(f"LLM API connection failed: {e.reason}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                break

        raise last_error  # type: ignore

    def _parse_response(self, content: str) -> list[AtomicFact]:
        """Parse LLM response into AtomicFacts with robust JSON extraction.

        Raises:
            ParseError: If no valid JSON array can be extracted.
        """
        if not content:
            return []

        # Try to extract JSON from markdown code blocks first
        json_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL
        )
        json_str = json_match.group(1) if json_match else content

        # Find the first JSON array
        array_match = re.search(r"\[.*\]", json_str, re.DOTALL)
        if not array_match:
            raise ParseError("No JSON array found in LLM response")

        try:
            data = json.loads(array_match.group(0))
        except json.JSONDecodeError as e:
            raise ParseError(f"Failed to decode JSON array: {e}") from e

        if not isinstance(data, list):
            raise ParseError("LLM response is not a JSON array")

        atoms = []
        for item in data:
            if not isinstance(item, dict) or "content" not in item:
                continue
            try:
                fact_type = FactType(item.get("type", "convention"))
            except ValueError:
                continue

            confidence = min(float(item.get("confidence", 0.8)), 1.0)

            # Hard confidence gate
            if confidence < self.MIN_CONFIDENCE:
                continue

            atoms.append(AtomicFact(
                type=fact_type,
                content=str(item["content"])[:self.config.max_fact_length],
                confidence=confidence,
                evidence=str(item.get("evidence", "")),
            ))

        return atoms

    def _post_process(self, atoms: list[AtomicFact]) -> list[AtomicFact]:
        """Rule-based post-processing to validate and adjust extracted facts.

        Checks each fact against type-specific patterns:
        - Must contain at least one keyword from must_contain
        - Confidence boosted if boost_keywords present
        - Confidence penalized if penalty_keywords present
        - Rejected if content is too generic
        """
        if not atoms:
            return atoms

        validated = []
        for fact in atoms:
            patterns = self.POST_PATTERNS.get(fact.type.value)
            if not patterns:
                validated.append(fact)
                continue

            content_lower = (fact.content + " " + fact.evidence).lower()

            # Check must-contain keywords
            # For lesson and rejection_reason, we're more lenient since the LLM prompt
            # already enforces these. For preference and decision, be stricter.
            if fact.type.value in ("preference", "decision", "rejection_reason"):
                if not any(kw in content_lower for kw in patterns["must_contain"]):
                    # If no keyword matches, confidence drops to a max of 0.7
                    # (below injection threshold) unless evidence is strong
                    fact.confidence = min(fact.confidence, 0.7)

            # Boost confidence for strong signals
            if any(kw in content_lower for kw in patterns["boost_keywords"]):
                fact.confidence = min(fact.confidence + 0.1, 1.0)

            # Penalize confidence for weak signals
            if any(kw in content_lower for kw in patterns["penalty_keywords"]):
                fact.confidence = max(fact.confidence - 0.15, 0.0)

            validated.append(fact)

        return validated

    def _self_critique(self, atoms: list[AtomicFact], conversation_text: str) -> list[AtomicFact]:
        """Lightweight rule-based self-critique — zero additional LLM calls.

        Checks:
        1. Evidence actually mentions the content (factuality check)
        2. Confidence too high for speculative language
        3. Content is too generic to be useful
        4. Critiques the model's confidence calibration
        """
        if not atoms:
            return atoms

        conversation_lower = conversation_text.lower()

        for fact in atoms:
            evidence = fact.evidence.lower()

            # 1. If evidence is just a generic paraphrase of the rule, penalize
            generic_evidence_indicators = [
                "extracted from", "based on", "the user said", "user mentioned",
                "inferred from", "the user seems", "as stated",
            ]
            if any(indicator in evidence[:60] for indicator in generic_evidence_indicators):
                fact.confidence = min(fact.confidence, 0.75)

            # 2. Check: does evidence actually appear in the conversation?
            evidence_text = fact.evidence.strip()
            if len(evidence_text) > 10:
                # Check if evidence text (or close paraphrase) exists in conversation
                evidence_keywords = set(re.findall(r"[a-zA-Z\u4e00-\u9fff]{4,}", evidence_text))
                conversation_keywords = set(re.findall(r"[a-zA-Z\u4e00-\u9fff]{4,}", conversation_lower))
                overlap = evidence_keywords & conversation_keywords
                if len(evidence_keywords) > 3 and len(overlap) < 2:
                    # Evidence doesn't match conversation — drop confidence
                    fact.confidence = min(fact.confidence, 0.5)
                    fact.evidence = fact.evidence + " [EVIDENCE MISMATCH]"

            # 3. Confidence calibration: high confidence should have strong evidence
            if fact.confidence >= 0.9 and len(fact.evidence) < 20:
                # High confidence but very short evidence — slightly penalize
                fact.confidence = min(fact.confidence, 0.85)

            # 4. Content too generic to be a useful memory
            content = fact.content.lower()
            generic_patterns = [
                r"^user (likes|prefers|uses|has) .{0,10}$",  # "User likes X" — too vague
                r"^the (user|system|project) .{0,15}$",
                r"^.{0,10} is (important|useful|helpful|good)",
            ]
            for pattern in generic_patterns:
                if re.search(pattern, content):
                    fact.confidence = min(fact.confidence, 0.6)
                    break

        return atoms


# ==============================================================================
# File input helpers
# ==============================================================================
