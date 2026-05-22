---
name: pam-os-memory
description: Use PAM-OS as the user's local long-term memory for Codex. Trigger when the user asks to continue prior work, refer to preferences, project history, prior decisions, long-term goals, answer style, or asks Codex to remember/capture stable information. Prefer PAM-OS MCP tools when available; use REST only when configured; use CLI only as a fallback.
---

# PAM-OS Memory

PAM-OS provides local-first memory through SQLite plus MCP, REST, and CLI adapters. Use it as a pre-answer read layer and a post-answer write layer, not as a replacement for normal task reasoning.

## Adapter Priority

Use adapters in this order:

1. MCP tools from the `pam-os-memory` server.
2. REST API only when a local PAM-OS REST server is configured and reachable.
3. CLI commands only as a fallback when MCP and REST are unavailable.

Do not start a long-running REST server unless the user asks for server setup. Do not overwrite or delete the user's memory database unless explicitly instructed.

## MCP Tools

Prefer these tools when available:

- `prepare_context`: read memory before answering history-, preference-, or project-dependent tasks.
- `capture_memory`: store stable user preferences, goals, project decisions, style guidance, or corrections.
- `record_behavior_choice`: record choices when the user chooses, rejects, or defers options.
- `consolidate_memory`: promote recent evidence into profile traits after meaningful batches.
- `get_profile`: read stable user profile traits when profile context is needed.
- `search_memory`: search stored memories for explicit memory lookup requests.
- `inspect_memory` and `get_storage_stats`: diagnostics only.

When `prepare_context` returns a package, use `package.content` as private working context. Do not paste the whole package to the user unless asked.

## Before Answering

Call `prepare_context` when the task depends on:

- ongoing projects or "continue where we left off"
- personal preferences, constraints, long-term goals, style, or prior decisions
- "according to my preference", "remember what I said", or similar history-dependent phrasing

Skip memory for generic one-off factual questions unless the user explicitly requests memory.

## After Answering

Capture stable information only:

- preferences: "I prefer self-hosted tools"
- goals: "My goal is to build..."
- project decisions: "We decided to use SQLite FTS5"
- style guidance: "Answer more directly next time"
- corrections: "That is not my preference"

Skip transient chat, secrets, credentials, and medical/legal/financial sensitive details unless the user explicitly asks to store them.

## Fallbacks

If MCP is unavailable and REST is configured, use the REST equivalents:

- `POST /context/prepare`
- `POST /memory/capture`
- `POST /behavior/choice`
- `POST /memory/consolidate`
- `GET /profile`

If only CLI is available, read `config.toml` from this skill directory when present and run the configured local PAM-OS CLI command. CLI is the fallback path because it may require shell execution approval.
