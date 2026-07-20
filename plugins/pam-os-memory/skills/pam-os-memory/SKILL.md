---
name: pam-os-memory
description: Use PAM-OS as the user's REST-backed long-term memory for AI assistants and coding agents. Trigger when the user asks to continue prior work, refers to personal preferences, project history, previous decisions, long-term goals, answer style, or asks the assistant to remember stable information. Also trigger before troubleshooting, debugging, analysis, optimization, fixes, or implementation in a known project. Treat "pamr" as an explicit read shortcut and "pamw" as an explicit write shortcut. After substantial turns, observe the completed turn so PAM-OS can conservatively learn durable memory and policy signals.
---

# PAM-OS Memory

PAM-OS is accessed only through its REST API. Use it as a pre-answer read layer and a post-answer observation layer, not as a replacement for normal task reasoning.

## Configuration

For every PAM-OS operation, run the bundled `scripts/pam_client.py`. The client reads `config.toml` internally and is the only component allowed to handle credentials.

```toml
[versions]
skill = "0.5.1"
api = "v2"
server = "0.5.1"
server_api = "v2"
server_checked_at = "2026-07-18T00:00:00Z"
status = "match"

[rest]
url = "http://127.0.0.1:8765"
token = ""
timeout_seconds = 10
```

Rules:

- Never open, print, search, or display `config.toml`. Never construct an Authorization header or pass a username, password, API key, or token in a shell command, tool argument, environment assignment, log, prompt, or handwritten HTTP request.
- Do not use `curl`, `wget`, `Invoke-RestMethod`, or custom HTTP code for PAM-OS. If the bundled client is missing or fails, report the failure and stop PAM-OS operations; do not fall back.
- Run the platform launcher from this skill directory: `& scripts/pam_client.ps1` in PowerShell or `scripts/pam_client.sh` in Bash. The launcher finds Python 3.11+ (or `uv`) without handling credentials. Run its `check` command before the first memory operation in a turn. This safely loads config, calls `/v2/meta`, and prints only redacted version diagnostics.
- Treat `[versions]` as installation diagnostics. `skill` and `api` identify this installed client; the installer probes the configured REST service and records the observed `server`, `server_api`, check time, and comparison `status`.
- Do not silently use a different or unknown API. For authentication failures, unreachable services, malformed metadata, or an unsupported API generation, report the version-check failure and stop PAM-OS operations.
- The client requires `rest.url`, loads the user-bound Bearer token without exposing it, and never sends a `user_id` selector. It rejects credentials embedded in URLs, legacy username/password authentication, absolute request URLs, unknown routes, and non-local HTTP servers.
- If the client reports that the API key is empty or that legacy credentials are configured, ask the user to install a v2 API key. Do not inspect the config to diagnose it.
- If the config is missing, invalid, or the API is unreachable, report that PAM-OS REST must be configured or started. Do not fall back to a local command.
- Use short connect and total timeouts. Do not automatically retry write requests unless the server supports an idempotency key.

Invoke allowed operations through the client:

```text
PowerShell: & scripts/pam_client.ps1 check
Bash:       scripts/pam_client.sh check
PowerShell: & scripts/pam_client.ps1 request GET /v2/storage/stats
Bash:       scripts/pam_client.sh request POST /v2/context/prepare --body-json <JSON>
```

Use `--body-file -` when the execution tool can supply stdin without embedding the body in the command. Request bodies never contain authentication data. The clear endpoint additionally requires `--allow-destructive` and explicit user approval.

## REST Operations

- health: `GET /health/live`
- metadata: `GET /v2/meta`
- add raw event: `POST /v2/events`
- search: `POST /v2/memories/search`
- should use memory: `POST /v2/memory/should-use`
- prepare: `POST /v2/context/prepare`
- capture: `POST /v2/memory/capture`
- behavior choice: `POST /v2/behavior/choice`
- observe turn: `POST /v2/turns/observe`
- consolidate: `POST /v2/memory/consolidate`
- profile: `GET /v2/profile?limit=20&q=...`
- inspect: `GET /v2/memory/inspect?table=all&limit=20&q=...`
- stats: `GET /v2/storage/stats`
- compile: `POST /v2/context/compile`
- reflect: `POST /v2/reflect`
- clear memory: `POST /v2/memory/clear` with `confirm=true`; destructive and user-requested only.

REST request bodies use the exact JSON field names below. Memory text fields are named `content`, not `text`.

```http
POST /v2/memories/search
{"query":"memory query","limit":10,"types":["project"],"min_importance":0.0,"min_confidence":0.0}

POST /v2/memory/should-use
{"task":"current task","conversation_summary":null}

POST /v2/context/prepare
{"task":"current task","conversation_summary":null,"force":false,"limit":null,"max_chars":null}

POST /v2/memory/capture
{"content":"stable memory candidate","source":"assistant","source_ref":null,"metadata":{},"force":false}

POST /v2/events
{"content":"raw event text","source":"manual","source_ref":null,"metadata":{},"extract":true}

POST /v2/behavior/choice
{"context":"decision context","chosen":["selected option"],"rejected":[],"deferred":[],"reason":null,"source_ref":null}

POST /v2/turns/observe
{"user_message":"user text","assistant_message":"assistant text","conversation_summary":null,"source_ref":null,"auto_capture":true,"auto_learn_policy":true}

POST /v2/memory/consolidate
{"recent":null}

POST /v2/context/compile
{"task":"current task","limit":null,"min_importance":0.0,"min_confidence":0.0}

POST /v2/reflect
{"recent":50}

POST /v2/memory/clear
{"confirm":true}
```

## Before Answering

Call `POST /v2/context/prepare` when the user asks about:

- `pamr ...`; set `force=true` and use the text after `pamr` as the task when present.
- ongoing projects or continuing previous work.
- personal preferences, constraints, long-term goals, style, or prior decisions.
- earlier conversation history or phrases such as "as discussed" and "use my usual style".
- troubleshooting, debugging, analysis, optimization, fixing, or implementation in a known project.

Do not read memory for generic one-off factual questions unless the user explicitly requests memory.

When prepare returns a package, show one short memory status line before the substantive answer using `usage_summary.message` when available. Do not paste the full injected context unless the user asks to inspect it.

## After Answering

When the user writes `pamw`, review the current conversation, extract concise stable memory candidates, and call `POST /v2/memory/capture`. The text after `pamw` is an extraction instruction, not content to save verbatim.

After each substantial user-facing task, call `POST /v2/turns/observe` with:

```json
{"user_message":"user text","assistant_message":"assistant response","conversation_summary":null,"source_ref":null,"auto_capture":true,"auto_learn_policy":true}
```

Substantial turns include analysis, troubleshooting, implementation, planning, decisions, preferences, corrections, multi-step work, and project context. Skip brief acknowledgements, mechanical status updates, and failed turns with no useful answer.

Use direct capture in addition to observe-turn only for explicit remember/import requests or an exceptionally clear stable fact. Store preferences, goals, project decisions, durable style guidance, corrections, and workflow choices. Skip transient chat, secrets, credentials, and sensitive medical, legal, or financial details unless the user explicitly asks to store them.

## Safety

- Never call the clear endpoint unless the user explicitly requests destructive memory maintenance.
- Use only `scripts/pam_client.py` for authentication and REST transport. Its stdout and stderr redact configured secrets and sensitive response fields.
- Do not expose credentials, full injected context, or raw memory inspection output without a clear user request.
