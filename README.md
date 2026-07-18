<div align="center">
  <h1>PAM-OS</h1>
  <p><strong>Personal AI Memory OS: a local-first, REST-only memory runtime for AI agents.</strong></p>
  <p>
    <a href="README.zh-CN.md">简体中文</a> ·
    <a href="docs/usage.md">Documentation</a> ·
    <a href="https://github.com/danzhewuju/PAM-OS">GitHub</a>
  </p>
  <p>
    <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache_2.0-blue" /></a>
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB" />
    <img alt="SQLite" src="https://img.shields.io/badge/SQLite-local--first-003B57" />
    <img alt="REST" src="https://img.shields.io/badge/REST-required-009688" />
  </p>
</div>

---

PAM-OS gives assistants a durable memory service they can call before and after a task. It stores raw events, extracts structured memories, retrieves relevant context, consolidates stable profile traits, learns when memory should be used, and returns prompt-ready context packages through a versioned REST API.

```text
AI client / skill
  -> PAM-OS REST API (/v1)
  -> PersonalMemoryRuntime
  -> Adaptive policy + provider pipeline
  -> SQLite MemoryStore
  -> Context package / capture result / profile
```

![PAM-OS memory architecture](docs/diagrams/memory-architecture.svg)

## Why PAM-OS?

- **Local-first storage**: one personal SQLite database, controlled by the user.
- **REST-only integration**: clients use one stable HTTP boundary instead of local process execution.
- **Prompt-ready retrieval**: `prepare` decides whether memory is needed and returns budgeted context.
- **Selective capture**: stable preferences, goals, project decisions, style guidance, and corrections are retained while transient chat is skipped.
- **Profile consolidation**: repeated evidence and behavior choices can become stable profile traits.
- **Adaptive policy memory**: learned signals improve when PAM-OS reads, captures, or suppresses memory.
- **Replaceable providers**: policy, extraction, retrieval, reranking, and consolidation remain protocol-agnostic behind the REST service.

## Quick Start

Requirements:

- Python 3.11 or newer
- SQLite with FTS5 when available
- `uv` recommended

Install dependencies and start the API:

```bash
uv sync
export PAM_OS_DB="$HOME/.pam-os/memory.sqlite3"
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

Check liveness and API metadata:

```bash
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/v1/meta
```

The interactive OpenAPI documentation is available at `http://127.0.0.1:8765/docs`.

## Recommended Agent Workflow

Prepare memory context before a history-dependent task:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/context/prepare \
  -H 'Content-Type: application/json' \
  -d '{"task":"Plan the next PAM-OS milestone based on my preferences.","force":false}'
```

Observe the completed turn after a substantial answer:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/turns/observe \
  -H 'Content-Type: application/json' \
  -d '{"user_message":"I prefer local-first systems.","assistant_message":"Understood.","auto_capture":true,"auto_learn_policy":true}'
```

Use direct capture for explicit remember/import requests:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/memory/capture \
  -H 'Content-Type: application/json' \
  -d '{"content":"The user prefers local-first, lightweight, controllable designs.","source":"assistant","force":true}'
```

## Plugin and Skill

The packaged `pam-os-memory` skill tells Codex, Claude Code, OpenCode, and Hermes when to prepare, capture, and observe memory. Its `config.toml` records the installed skill/API versions, the server version observed during installation, and the REST client settings:

```toml
[versions]
skill = "0.4.2"
api = "v1"
server = "0.4.2"
server_api = "v1"
server_checked_at = "2026-07-18T00:00:00Z"
status = "match"

[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
timeout_seconds = 10
```

Install from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/install.sh | bash
```

Install from the current checkout:

```bash
./scripts/install.sh --repo-dir "$PWD" --yes
```

Windows PowerShell:

```powershell
.\scripts\install.ps1 --repo-dir $PWD --yes
```

The two platform installers handle both first install and update. With no target flags they detect existing integrations and update all installed targets; otherwise a first install selects targets interactively or defaults to Codex with `--yes`. The installer reuses an existing skill's REST URL, username, password, and timeout, refreshes the managed checkout, probes server metadata, and writes an observable version snapshot. Explicit command-line options and `PAM_OS_REST_*` environment variables take precedence. REST credentials are written with restrictive file permissions where supported. For remote servers, use HTTPS and avoid passing passwords in shell history.

## REST API

Canonical endpoints use the `/v1` prefix. Unversioned paths from v0.3 remain as hidden compatibility aliases for one migration window.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health/live` | Public process liveness. |
| `GET` | `/v1/health/ready` | Authenticated database readiness. |
| `GET` | `/v1/meta` | Runtime and API version metadata. |
| `POST` | `/v1/events` | Add a raw event and optionally extract memories. |
| `POST` | `/v1/memories/search` | Search memories with type and score filters. |
| `POST` | `/v1/memory/should-use` | Decide whether a task should use memory. |
| `POST` | `/v1/context/prepare` | Prepare prompt-ready memory context. |
| `POST` | `/v1/memory/capture` | Selectively capture stable memory. |
| `POST` | `/v1/behavior/choice` | Record behavior evidence. |
| `POST` | `/v1/turns/observe` | Observe a completed chat turn. |
| `POST` | `/v1/memory/consolidate` | Consolidate evidence into profile traits. |
| `GET` | `/v1/profile` | Read profile traits. |
| `POST` | `/v1/context/compile` | Compile context directly from retrieval. |
| `POST` | `/v1/reflect` | Build context from recent memories. |
| `GET` | `/v1/storage/stats` | Read storage diagnostics. |
| `GET` | `/v1/memory/inspect` | Inspect memory tables and traces. |
| `POST` | `/v1/memory/clear` | Clear all memory after explicit confirmation. |

Request models reject unknown fields, reject oversized request bodies, and constrain text sizes, scores, and result limits. API validation and runtime/storage failures return structured error payloads.

## Security Model

PAM-OS v0.4 is a personal, single-database service. Client-supplied tenant IDs were removed because they did not constitute an authorization boundary.

Enable Basic Auth in `config/pam-os.toml`:

```toml
[server]
host = "127.0.0.1"
port = 8765
auth_enabled = true
auth_username = "user"
auth_password = "change-me"
```

Or use environment variables:

```bash
export PAM_OS_AUTH_ENABLED=true
export PAM_OS_AUTH_USERNAME=user
export PAM_OS_AUTH_PASSWORD=change-me
```

Basic Auth must be protected by HTTPS when the service is reachable beyond localhost. Put PAM-OS behind a TLS reverse proxy or private network; do not expose plain HTTP credentials to the public internet.

## SQLite and Concurrency

The REST service opens short-lived SQLite connections, enables foreign keys, uses a busy timeout, and initializes the database in WAL mode. This supports normal personal-agent concurrency while keeping the storage model lightweight.

## Docker

```bash
docker build -t pam-os .
docker volume create pam-os-data
docker run -d --name pam-os \
  -p 8765:8765 \
  -v pam-os-data:/data \
  -e PAM_OS_AUTH_ENABLED=true \
  -e PAM_OS_AUTH_USERNAME=user \
  -e PAM_OS_AUTH_PASSWORD=change-me \
  pam-os
```

The container runs the ASGI factory directly and stores data at `/data/memory.sqlite3`.

## Configuration

Copy the example configuration:

```bash
cp config/pam-os.example.toml config/pam-os.toml
```

Environment variables override `config/pam-os.toml`, which overrides built-in defaults:

```bash
export PAM_OS_DB="$HOME/.pam-os/memory.sqlite3"
export PAM_OS_CONFIG="/path/to/pam-os.toml"
export PAM_OS_HOST="0.0.0.0"
export PAM_OS_PORT="8765"
```

See [config/pam-os.example.toml](config/pam-os.example.toml) for all runtime, context, consolidation, retrieval, extraction, and provider settings.

## Project Structure

```text
src/pam_os/
  api.py             # REST API, request validation, auth, health, errors
  runtime.py         # protocol-agnostic memory runtime
  store.py           # SQLite schema, writes, retrieval, inspection
  orchestrator.py    # policy, retrieval, reranking, and context budgets
  providers.py       # replaceable provider interfaces
  adaptive_policy.py # learned signals plus rule fallback
  rule_provider.py   # default local providers
  extractor.py       # rule-based extraction
  context.py         # prompt-ready context compiler
```

## Development

```bash
uv sync --extra dev
uv run pytest
```

Quality evaluation remains a Python development API through `pam_os.quality.evaluate_quality_cases`; it is not exposed as a product command.

## Update

Run the same installer again. It detects existing targets, updates the managed checkout, reinstalls integrations, and refreshes the skill/server version snapshot:

```bash
curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/install.sh | bash
```

## License

PAM-OS is licensed under the [Apache License 2.0](LICENSE).
