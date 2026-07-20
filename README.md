<div align="center">
  <h1>PAM-OS</h1>
  <p><strong>Personal AI Memory OS — a local-first memory service for AI assistants and coding agents.</strong></p>
  <p>
    <a href="README.zh-CN.md">简体中文</a> ·
    <a href="docs/usage.md">Usage guide</a> ·
    <a href="https://github.com/danzhewuju/PAM-OS">GitHub</a>
  </p>
  <p>
    <a href="LICENSE"><img alt="Apache-2.0 license" src="https://img.shields.io/badge/License-Apache_2.0-blue" /></a>
    <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB" />
    <img alt="FastAPI" src="https://img.shields.io/badge/API-FastAPI-009688" />
    <img alt="SQLite" src="https://img.shields.io/badge/Storage-SQLite-003B57" />
  </p>
</div>

---

PAM-OS gives an AI client durable personal memory behind a versioned REST API. It can capture stable facts and preferences, retrieve relevant memories before a task, consolidate repeated evidence into profile traits, and learn signals that influence when memory should be read or written.

PAM-OS is a multi-user memory service. Bearer API keys bind every caller to a fixed user, and each user's data is stored in a separate owner-bound SQLite database.

```text
AI client / pam-os-memory skill
              |
              v
       FastAPI REST API (/v2)
              |
              v
  Auth context + user store routing
              |       |       |
    policy  retrieval  extraction
       |       |       |
              v
   Per-user SQLite MemoryStore
```

![PAM-OS memory architecture](docs/diagrams/memory-architecture.svg)

## What is included

- A FastAPI service with canonical `/v2` endpoints.
- SQLite storage with WAL mode, foreign keys, FTS5 when available, and a non-FTS search fallback.
- Rule-based memory extraction, retrieval, reranking, adaptive read/write policy, and profile consolidation.
- Prompt-ready context preparation with result and character budgets.
- User-bound Bearer API keys with scopes, revocation, and identity audit logs.
- A `pam-os-memory` skill/plugin package for Codex, Claude Code, OpenCode, and Hermes.
- Docker packaging and cross-platform agent-integration installers.

## Current scope

- A user can have separate API keys for Codex, Claude, OpenCode, Hermes, or other agents.
- SQLite remains the local-first storage backend; centralized large-scale deployments can add another storage adapter later.
- REST is the product boundary. The repository does not provide a `pam-os` product CLI.
- `scripts/` intentionally contains only the two platform installers: `install.sh` and `install.ps1`.
- Quality evaluation is available as the Python development API `pam_os.quality.evaluate_quality_cases`; it is not a standalone command or script.
- Rule-based extraction is the server default. The LLM extractor is an injectable Python provider and falls back to rules; the REST server does not create an LLM client from configuration alone.

## Quick start

Requirements:

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/) (recommended)

Install the package and start the API from the repository root:

```bash
uv sync
export PAM_OS_BOOTSTRAP_TOKEN='replace-with-a-long-random-secret'
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

Unless configured otherwise, PAM-OS creates `~/.pam-os/control.sqlite3` plus one memory database below `~/.pam-os/users/` for each user.

Verify the service:

```bash
curl -sS http://127.0.0.1:8765/health/live
curl -sS -X POST http://127.0.0.1:8765/v2/admin/users \
  -H "Authorization: Bearer $PAM_OS_BOOTSTRAP_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","principal_name":"admin","scopes":["admin:users","api_keys:manage","memory:read","memory:write","memory:delete","memory:inspect"]}'
```

The provisioning response returns the user's API key exactly once. Store it securely, configure clients with it, and remove `PAM_OS_BOOTSTRAP_TOKEN` after creating a user-bound administrative key.

Swagger UI is available at `http://127.0.0.1:8765/docs`.

## Basic memory loop

Prepare relevant context before a history-dependent task:

```bash
curl -sS -X POST http://127.0.0.1:8765/v2/context/prepare \
  -H 'Authorization: Bearer <api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"task":"Continue the project using my previous decisions.","force":false}'
```

Observe a completed substantial turn so stable information can be captured and policy signals can be learned:

```bash
curl -sS -X POST http://127.0.0.1:8765/v2/turns/observe \
  -H 'Authorization: Bearer <api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"user_message":"I prefer local-first tools.","assistant_message":"I will keep the design local-first.","auto_capture":true,"auto_learn_policy":true}'
```

Use direct capture when the user explicitly asks the agent to remember something:

```bash
curl -sS -X POST http://127.0.0.1:8765/v2/memory/capture \
  -H 'Authorization: Bearer <api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"content":"The user prefers local-first, lightweight tools.","source":"assistant","force":true}'
```

See [docs/usage.md](docs/usage.md) for request examples, response behavior, validation rules, and the recommended agent workflow.

## REST API

`GET /health/live` is public. Every `/v2` endpoint requires a Bearer API key or the one-time bootstrap credential.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/v2/health/ready` | Check database readiness. |
| `GET` | `/v2/meta` | Read runtime and API versions. |
| `GET` | `/v2/me` | Read the authenticated user, principal, key, and scopes. |
| `POST` | `/v2/admin/users` | Provision a user and initial API key. |
| `POST` | `/v2/events` | Store a raw event and optionally extract memories. |
| `POST` | `/v2/memories/search` | Search memories with type and score filters. |
| `POST` | `/v2/memory/should-use` | Decide whether a task should read memory. |
| `POST` | `/v2/context/prepare` | Return a policy-gated, prompt-ready context package. |
| `POST` | `/v2/memory/capture` | Selectively capture stable memory. |
| `POST` | `/v2/behavior/choice` | Record chosen, rejected, or deferred options. |
| `POST` | `/v2/turns/observe` | Observe a completed conversation turn. |
| `POST` | `/v2/memory/consolidate` | Consolidate evidence into profile traits. |
| `GET` | `/v2/profile` | Query profile traits. |
| `POST` | `/v2/context/compile` | Retrieve and compile context without policy gating. |
| `POST` | `/v2/reflect` | Build context from recent memories. |
| `GET` | `/v2/storage/stats` | Read storage diagnostics. |
| `GET` | `/v2/memory/inspect` | Inspect stored records and quality traces. |
| `POST` | `/v2/memory/clear` | Clear all memory after explicit confirmation. |

The incompatible v2 API does not expose v1 or unversioned compatibility aliases.

## Configuration

Copy the complete example before starting the service:

```bash
cp config/pam-os.example.toml config/pam-os.toml
```

PAM-OS loads `config/pam-os.toml` from the current working directory by default. `PAM_OS_CONFIG` can point to another file. Supported environment overrides are:

```text
PAM_OS_DATA_DIR
PAM_OS_CONTROL_DB
PAM_OS_RUNTIME_CACHE_SIZE
PAM_OS_CONFIG
PAM_OS_HOST
PAM_OS_PORT
PAM_OS_BOOTSTRAP_TOKEN
```

Environment variables override TOML values, which override built-in defaults. When starting Uvicorn manually, its `--host` and `--port` arguments control the actual listener; the Docker image reads `PAM_OS_HOST` and `PAM_OS_PORT` for those arguments.

### Authentication and remote access

Configure a one-time bootstrap credential in `config/pam-os.toml`:

```toml
[server]
host = "127.0.0.1"
port = 8765
bootstrap_token = "replace-with-a-long-random-secret"
```

Or set `PAM_OS_BOOTSTRAP_TOKEN`. Use it only to provision the first user and user-bound admin key, then remove it. If the service is reachable beyond localhost, place it behind HTTPS or a trusted private network. Bearer API keys must not be sent over public plain HTTP.

## Agent integration

The installers configure the `pam-os-memory` integration; they do not install or run the REST service itself. Start or deploy PAM-OS first, then install the integration for the clients you use.

From the current checkout on macOS or Linux:

```bash
./scripts/install.sh --codex --repo-dir "$PWD" --rest-token '<api-key>' --yes
```

Supported targets are `codex`, `claude`, `opencode`, and `hermes`. Use another target flag, repeat `--target`, or pass `--all` as needed:

```bash
./scripts/install.sh --all --repo-dir "$PWD" --yes
```

Windows PowerShell uses the same long options:

```powershell
.\scripts\install.ps1 --codex --repo-dir $PWD --yes
```

To install or update from GitHub on macOS/Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/install.sh | bash
```

Run `./scripts/install.sh --help` or `.\scripts\install.ps1 --help` for all destination, REST connection, update, and non-interactive options. Existing installations reuse their REST settings unless explicit options or `PAM_OS_REST_*` variables override them.

## Docker

Build and run a local instance:

```bash
docker build -t pam-os .
docker volume create pam-os-data
docker run -d --name pam-os \
  -p 127.0.0.1:8765:8765 \
  -v pam-os-data:/data \
  -e PAM_OS_BOOTSTRAP_TOKEN='replace-with-a-long-random-secret' \
  pam-os
```

The container stores the control database and per-user memory databases below `/data` and exposes the API on port `8765`. Set `PAM_OS_BOOTSTRAP_TOKEN` for first-user provisioning and terminate TLS at the deployment boundary before allowing remote access.

## Repository layout

```text
src/pam_os/                 REST API and memory runtime
skills/pam-os-memory/       Standalone agent skill package
plugins/pam-os-memory/      Codex plugin package
scripts/install.sh          macOS/Linux installer and updater
scripts/install.ps1         Windows installer and updater
config/pam-os.example.toml  Complete server configuration example
tests/                      Runtime, API, installer, and version tests
eval/                       Quality-evaluation case data
docs/                       Usage, architecture, and design documents
```

Important runtime modules:

```text
api.py               FastAPI v2 routes, scopes, validation, and error handling
identity.py          Users, principals, Bearer API keys, and identity audit log
tenancy.py           Authenticated user-to-runtime routing and store owner checks
runtime.py           Protocol-agnostic PersonalMemoryRuntime
store.py             SQLite schema, persistence, retrieval, and inspection
orchestrator.py      Policy, retrieval, reranking, and context budgeting
adaptive_policy.py   Learned policy signals with rule-based fallback
adaptive_learning.py Turn observation and policy-learning loop
rule_provider.py     Default local policy, reranker, and consolidator
extractor.py         Default rule-based memory extractor
context.py           Prompt-ready context compiler
```

## Development

Install development dependencies and run the test suite:

```bash
uv sync --extra dev
uv run pytest
```

The tests cover the memory lifecycle, adaptive policy, profile consolidation, REST validation and authentication, both platform installers, and version consistency.

## License

PAM-OS is licensed under the [Apache License 2.0](LICENSE).
