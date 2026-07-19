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

The current project is a single-user, single-database service. Data is stored in a user-controlled SQLite file, and the default implementation runs locally without an external model or vector database.

```text
AI client / pam-os-memory skill
              |
              v
       FastAPI REST API (/v1)
              |
              v
     PersonalMemoryRuntime
       |       |       |
    policy  retrieval  extraction
       |       |       |
              v
        SQLite MemoryStore
```

![PAM-OS memory architecture](docs/diagrams/memory-architecture.svg)

## What is included

- A FastAPI service with canonical `/v1` endpoints.
- SQLite storage with WAL mode, foreign keys, FTS5 when available, and a non-FTS search fallback.
- Rule-based memory extraction, retrieval, reranking, adaptive read/write policy, and profile consolidation.
- Prompt-ready context preparation with result and character budgets.
- Optional HTTP Basic Auth for protected endpoints.
- A `pam-os-memory` skill/plugin package for Codex, Claude Code, OpenCode, and Hermes.
- Docker packaging and cross-platform agent-integration installers.

## Current scope

- PAM-OS is a personal memory service, not a multi-tenant authorization system. Run a separate instance and database for each user.
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
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

Unless configured otherwise, PAM-OS creates its database at `~/.pam-os/memory.sqlite3`.

Verify the service:

```bash
curl -sS http://127.0.0.1:8765/health/live
curl -sS http://127.0.0.1:8765/v1/meta
```

Swagger UI is available at `http://127.0.0.1:8765/docs`.

## Basic memory loop

Prepare relevant context before a history-dependent task:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/context/prepare \
  -H 'Content-Type: application/json' \
  -d '{"task":"Continue the project using my previous decisions.","force":false}'
```

Observe a completed substantial turn so stable information can be captured and policy signals can be learned:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/turns/observe \
  -H 'Content-Type: application/json' \
  -d '{"user_message":"I prefer local-first tools.","assistant_message":"I will keep the design local-first.","auto_capture":true,"auto_learn_policy":true}'
```

Use direct capture when the user explicitly asks the agent to remember something:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/memory/capture \
  -H 'Content-Type: application/json' \
  -d '{"content":"The user prefers local-first, lightweight tools.","source":"assistant","force":true}'
```

See [docs/usage.md](docs/usage.md) for request examples, response behavior, validation rules, and the recommended agent workflow.

## REST API

`GET /health/live` is public. When Basic Auth is enabled, all other product endpoints require authentication.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/v1/health/ready` | Check database readiness. |
| `GET` | `/v1/meta` | Read runtime and API versions. |
| `POST` | `/v1/events` | Store a raw event and optionally extract memories. |
| `POST` | `/v1/memories/search` | Search memories with type and score filters. |
| `POST` | `/v1/memory/should-use` | Decide whether a task should read memory. |
| `POST` | `/v1/context/prepare` | Return a policy-gated, prompt-ready context package. |
| `POST` | `/v1/memory/capture` | Selectively capture stable memory. |
| `POST` | `/v1/behavior/choice` | Record chosen, rejected, or deferred options. |
| `POST` | `/v1/turns/observe` | Observe a completed conversation turn. |
| `POST` | `/v1/memory/consolidate` | Consolidate evidence into profile traits. |
| `GET` | `/v1/profile` | Query profile traits. |
| `POST` | `/v1/context/compile` | Retrieve and compile context without policy gating. |
| `POST` | `/v1/reflect` | Build context from recent memories. |
| `GET` | `/v1/storage/stats` | Read storage diagnostics. |
| `GET` | `/v1/memory/inspect` | Inspect stored records and quality traces. |
| `POST` | `/v1/memory/clear` | Clear all memory after explicit confirmation. |

Unversioned v0.3 routes remain as hidden compatibility aliases for migration. New clients should use `/v1` only.

## Configuration

Copy the complete example before starting the service:

```bash
cp config/pam-os.example.toml config/pam-os.toml
```

PAM-OS loads `config/pam-os.toml` from the current working directory by default. `PAM_OS_CONFIG` can point to another file. Supported environment overrides are:

```text
PAM_OS_DB
PAM_OS_CONFIG
PAM_OS_HOST
PAM_OS_PORT
PAM_OS_AUTH_ENABLED
PAM_OS_AUTH_USERNAME
PAM_OS_AUTH_PASSWORD
```

Environment variables override TOML values, which override built-in defaults. When starting Uvicorn manually, its `--host` and `--port` arguments control the actual listener; the Docker image reads `PAM_OS_HOST` and `PAM_OS_PORT` for those arguments.

### Authentication and remote access

Enable Basic Auth in `config/pam-os.toml`:

```toml
[server]
host = "127.0.0.1"
port = 8765
auth_enabled = true
auth_username = "user"
auth_password = "change-me"
```

Or use the corresponding `PAM_OS_AUTH_*` environment variables. If the service is reachable beyond localhost, place it behind HTTPS or a trusted private network. Basic Auth credentials must not be sent over public plain HTTP.

## Agent integration

The installers configure the `pam-os-memory` integration; they do not install or run the REST service itself. Start or deploy PAM-OS first, then install the integration for the clients you use.

From the current checkout on macOS or Linux:

```bash
./scripts/install.sh --codex --repo-dir "$PWD" --yes
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
  pam-os
```

The container stores its database at `/data/memory.sqlite3` and exposes the API on port `8765`. Add `PAM_OS_AUTH_*` environment variables and TLS at the deployment boundary before allowing remote access.

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
api.py               FastAPI routes, auth, validation, and error handling
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
