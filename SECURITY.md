# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in agent-memory, please report it
privately before disclosing it publicly.

**Do not open a public GitHub issue** — instead, send details to:

- Open a **GitHub Security Advisory** at:
  https://github.com/siar765/agent-memory/security/advisories/new
- Or email the maintainer directly (see GitHub profile for contact)

We will acknowledge receipt within 48 hours and aim to release a fix within
7 days for confirmed vulnerabilities.

## Scope

This policy covers the agent-memory codebase itself (the Python package and CLI).
It does **not** cover:

- The LLM APIs or providers used for fact extraction
- Third-party dependencies in your broader system
- Data you store or process with agent-memory

## Responsible Disclosure

We ask that you:

1. Provide sufficient detail to reproduce the issue
2. Allow reasonable time for a fix before public disclosure
3. Do not exploit the vulnerability beyond demonstrating its existence

We will:

1. Acknowledge receipt within 48 hours
2. Keep you informed of progress
3. Credit you in the release notes (unless you prefer to remain anonymous)

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | ✅ Active development |

## Safety Considerations

Agent-memory processes conversation text and sends it to configured LLM APIs.

- **API keys**: Store them in environment variables, never in code or config files
- **Sensitive data**: Be aware that conversation text sent to the LLM API may be
  visible to the API provider
- **Local storage**: Extracted facts are stored in plain JSONL files — ensure
  appropriate access controls on the data directory
