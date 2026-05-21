---
name: pam-os-memory
description: Use PAM-OS as the user's local long-term memory for Codex. Trigger when the user asks to continue prior work, refer to personal preferences, project history, previous decisions, long-term goals, answer style, or asks Codex to remember/capture stable information. Read this skill's config.toml first; default to local CLI mode and use REST API only when the skill config sets mode = "rest".
---

# PAM-OS Memory

PAM-OS provides local-first memory through SQLite plus CLI, REST, and MCP adapters. Use it as a pre-answer read layer and a post-answer write layer, not as a replacement for normal task reasoning.

## Mode Selection

Before any PAM-OS operation, read `config.toml` from this skill directory:

```text
config.toml
```

If the config file is missing, unreadable, or does not set a valid mode, use CLI mode.

Supported modes:

- `cli`: default. Run local `memory` CLI commands from the PAM-OS repository.
- `rest`: call the PAM-OS REST API at `[rest].url`.

Do not use MCP by default. Use MCP only if the user explicitly asks to configure or test MCP.

Do not start a long-running REST server unless the user asks for server setup. In REST mode, if the API is unreachable, report that the server must be started instead of silently falling back.

## Config Format

Expected `config.toml`:

```toml
mode = "cli"

[cli]
python = "3.12"
command = "memory"

[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
```

To switch the model to REST, change only:

```toml
mode = "rest"
```

## Operations

Use these recommended operations in either mode:

- prepare before answering when the task depends on user/project/history context.
- capture after stable user preferences, goals, project decisions, style guidance, or corrections appear.
- record behavior choices when the user chooses, rejects, or defers options.
- consolidate periodically to promote evidence into profile traits.
- read profile traits when stable user profile is needed.

REST endpoint equivalents:

- prepare: `POST /context/prepare`
- capture: `POST /memory/capture`
- behavior choice: `POST /behavior/choice`
- consolidate: `POST /memory/consolidate`
- profile: `GET /profile`

If REST `username` and `password` are non-empty, send HTTP Basic Auth on every REST request. If either value is empty, do not send an Authorization header.

## Before Answering

Call `prepare_context` when the user asks about:

- ongoing projects or "continue where we left off"
- personal preferences, constraints, long-term goals, style, or prior decisions
- "according to my preference", "remember what I said", or similar history-dependent phrasing

Do not read memory for generic one-off factual questions unless the user explicitly requests memory.

In CLI mode, run from the PAM-OS repo:

```powershell
uv run --python 3.12 memory prepare "<current task>" --json
```

In REST mode, call:

```powershell
$headers = @{}
if ("<username>" -and "<password>") {
  $pair = "<username>:<password>"
  $token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
  $headers.Authorization = "Basic $token"
}

Invoke-RestMethod `
  -Uri "<rest-url>/context/prepare" `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"task":"<current task>","force":false}'
```

When a context package is returned, use `package.content` as private working context. Do not paste the whole package to the user unless asked.

## After Answering

Capture stable information only:

- preferences: "I prefer self-hosted tools"
- goals: "My goal is to build..."
- project decisions: "We decided to use SQLite FTS5"
- style guidance: "Answer more directly next time"
- corrections: "That is not my preference"

Skip transient chat, secrets, credentials, medical/legal/financial sensitive details unless the user explicitly asks to store them.

In CLI mode:

```powershell
uv run --python 3.12 memory capture "<stable information>"
```

In REST mode:

```powershell
$headers = @{}
if ("<username>" -and "<password>") {
  $pair = "<username>:<password>"
  $token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
  $headers.Authorization = "Basic $token"
}

Invoke-RestMethod `
  -Uri "<rest-url>/memory/capture" `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"content":"<stable information>","force":false}'
```

Use `--force` only when the user explicitly asks to remember something and the automatic capture gate skips it.

## Behavior Choices

When the user chooses among alternatives, record the choice:

```powershell
uv run --python 3.12 memory behavior-choice `
  --context "<decision context>" `
  --chosen "<chosen option>" `
  --rejected "<rejected option>" `
  --reason "<optional reason>"
```

Run consolidation after meaningful batches of captures or choices:

```powershell
uv run --python 3.12 memory consolidate --recent 100
```

In REST mode, call `POST /behavior/choice` and `POST /memory/consolidate` with the equivalent JSON bodies.

## Safety

Keep PAM-OS local by default. Respect `PAM_OS_DB`, `PAM_OS_CONFIG`, and `--db` when present. Never overwrite or delete the user's database unless explicitly instructed.
