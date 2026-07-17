---
name: pam-os-memory
description: Use PAM-OS as the user's REST-backed long-term memory for AI assistants and coding agents. Trigger when the user asks to continue prior work, refers to personal preferences, project history, previous decisions, long-term goals, answer style, or asks the assistant to remember stable information. Also trigger before troubleshooting, debugging, analysis, optimization, fixes, or implementation in a known project. Treat "pamr" as an explicit read shortcut and "pamw" as an explicit write shortcut. After substantial turns, observe the completed turn so PAM-OS can conservatively learn durable memory and policy signals.
---

# PAM-OS Memory

PAM-OS is accessed only through its REST API. Use it as a pre-answer read layer and a post-answer observation layer, not as a replacement for normal task reasoning.

## Configuration

Read `config.toml` from this skill directory before every PAM-OS operation.

```toml
[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
timeout_seconds = 10
```

Rules:

- `rest.url` is required. Remove any trailing slash before joining endpoint paths.
- If both `username` and `password` are non-empty, send HTTP Basic Auth on every protected request.
- If either credential field is empty, do not send an Authorization header.
- Use HTTPS whenever the server is not bound to localhost.
- If the config is missing, invalid, or the API is unreachable, report that PAM-OS REST must be configured or started. Do not fall back to a local command.
- Use short connect and total timeouts. Do not automatically retry write requests unless the server supports an idempotency key.

## REST Operations

- health: `GET /health/live`
- metadata: `GET /v1/meta`
- add raw event: `POST /v1/events`
- search: `POST /v1/memories/search`
- should use memory: `POST /v1/memory/should-use`
- prepare: `POST /v1/context/prepare`
- capture: `POST /v1/memory/capture`
- behavior choice: `POST /v1/behavior/choice`
- observe turn: `POST /v1/turns/observe`
- consolidate: `POST /v1/memory/consolidate`
- profile: `GET /v1/profile?limit=20&q=...`
- inspect: `GET /v1/memory/inspect?table=all&limit=20&q=...`
- stats: `GET /v1/storage/stats`
- compile: `POST /v1/context/compile`
- reflect: `POST /v1/reflect`
- clear memory: `POST /v1/memory/clear` with `confirm=true`; destructive and user-requested only.

REST request bodies use the exact JSON field names below. Memory text fields are named `content`, not `text`.

```http
POST /v1/memories/search
{"query":"memory query","limit":10,"types":["project"],"min_importance":0.0,"min_confidence":0.0}

POST /v1/memory/should-use
{"task":"current task","conversation_summary":null}

POST /v1/context/prepare
{"task":"current task","conversation_summary":null,"force":false,"limit":null,"max_chars":null}

POST /v1/memory/capture
{"content":"stable memory candidate","source":"assistant","source_ref":null,"metadata":{},"force":false}

POST /v1/events
{"content":"raw event text","source":"manual","source_ref":null,"metadata":{},"extract":true}

POST /v1/behavior/choice
{"context":"decision context","chosen":["selected option"],"rejected":[],"deferred":[],"reason":null,"source_ref":null}

POST /v1/turns/observe
{"user_message":"user text","assistant_message":"assistant text","conversation_summary":null,"source_ref":null,"auto_capture":true,"auto_learn_policy":true}

POST /v1/memory/consolidate
{"recent":null}

POST /v1/context/compile
{"task":"current task","limit":null,"min_importance":0.0,"min_confidence":0.0}

POST /v1/reflect
{"recent":50}

POST /v1/memory/clear
{"confirm":true}
```

## Before Answering

Call `POST /v1/context/prepare` when the user asks about:

- `pamr ...`; set `force=true` and use the text after `pamr` as the task when present.
- ongoing projects or continuing previous work.
- personal preferences, constraints, long-term goals, style, or prior decisions.
- earlier conversation history or phrases such as "as discussed" and "use my usual style".
- troubleshooting, debugging, analysis, optimization, fixing, or implementation in a known project.

Do not read memory for generic one-off factual questions unless the user explicitly requests memory.

When prepare returns a package, show one short memory status line before the substantive answer using `usage_summary.message` when available. Do not paste the full injected context unless the user asks to inspect it.

## After Answering

When the user writes `pamw`, review the current conversation, extract concise stable memory candidates, and call `POST /v1/memory/capture`. The text after `pamw` is an extraction instruction, not content to save verbatim.

After each substantial user-facing task, call `POST /v1/turns/observe` with:

```json
{"user_message":"user text","assistant_message":"assistant response","conversation_summary":null,"source_ref":null,"auto_capture":true,"auto_learn_policy":true}
```

Substantial turns include analysis, troubleshooting, implementation, planning, decisions, preferences, corrections, multi-step work, and project context. Skip brief acknowledgements, mechanical status updates, and failed turns with no useful answer.

Use direct capture in addition to observe-turn only for explicit remember/import requests or an exceptionally clear stable fact. Store preferences, goals, project decisions, durable style guidance, corrections, and workflow choices. Skip transient chat, secrets, credentials, and sensitive medical, legal, or financial details unless the user explicitly asks to store them.

## Safety

- Never call the clear endpoint unless the user explicitly requests destructive memory maintenance.
- Do not expose credentials, full injected context, or raw memory inspection output without a clear user request.
- Keep remote PAM-OS deployments behind HTTPS and authentication.
