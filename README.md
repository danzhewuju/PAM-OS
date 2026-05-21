# Personal AI Memory OS MVP

This repository implements the first executable slice of `Personal Memory Runtime`:

```text
Raw Event -> Memory Extraction -> SQLite Memory Store -> Retrieval -> Context Compilation
```

The MVP is local-first and deliberately small. The runtime stores raw events forever, extracts structured memories, retrieves them with SQLite FTS5 when available, and compiles a prompt-ready context package.

## Architecture Diagram

Open the interactive architecture diagram: [docs/diagrams/memory-architecture.html](docs/diagrams/memory-architecture.html).

## Quick Start

For a full usage guide, see [docs/usage.md](docs/usage.md).
For model-client setup with Codex, Claude Code, CC Switch, and project Skills, see [docs/usage.md#65-加载到大模型客户端中使用](docs/usage.md#65-加载到大模型客户端中使用).

Install the PAM-OS memory skill for Codex or other supported clients:

```bash
curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/install-skill.sh | bash
```

The installer writes the skill to your user-level client directory and uses `~/.pam-os/memory.sqlite3` as the default shared local memory database.

Use the local CLI directly:

```powershell
uv run --python 3.12 memory init
uv run --python 3.12 memory add "我今天在思考 Personal AI Memory OS，倾向先做本地 REST 服务，不想一开始引入重型组件。"
uv run --python 3.12 memory search "Personal AI Memory OS 下一步实现"
uv run --python 3.12 memory compile "我现在想继续做 Personal AI Memory OS，下一步怎么做？"
uv run --python 3.12 memory stats
```

By default, data is stored in `~/.pam-os/memory.sqlite3` so multiple terminals and projects share the same local memory database. Override it with:

```powershell
$env:PAM_OS_DB = "C:\path\to\memory.sqlite3"
```

## Configuration

Copy the example config and edit local settings:

```powershell
Copy-Item config\pam-os.example.toml config\pam-os.toml
```

The runtime loads config in this order:

```text
CLI arguments > environment variables > config/pam-os.toml > built-in defaults
```

You can also point to a custom config file:

```powershell
$env:PAM_OS_CONFIG = "C:\path\to\pam-os.toml"
uv run --python 3.12 memory --config C:\path\to\pam-os.toml prepare "我继续做 PAM-OS"
```

Important sections:

- `[storage]`: SQLite database path.
- `[server]`: REST host and port.
- `[context]`: memory limits, context character budget, profile trait injection count.
- `[consolidation]`: how many recent memories/behavior events are scanned and how fast profile stability grows.
- `[orchestrator]`: thresholds for reading and capturing memory.
- `[retrieval]`: query term extraction limit.
- `[profile]`: default number of profile traits returned.

## CLI

```text
memory init
memory add <content> [--source manual] [--metadata-json {...}]
memory search <query> [--limit 10]
memory should-use <task>
memory prepare <task> [--force] [--limit 12] [--max-chars 4000]
memory capture <content> [--force]
memory behavior-choice --context <context> --chosen <option> [--rejected <option>] [--deferred <option>]
memory consolidate [--recent 100]
memory profile [--query <query>]
memory compile <task> [--limit 12]
memory reflect [--recent 50]
memory serve [--host 127.0.0.1] [--port 8765]
memory stats
```

For model integration, prefer the orchestrated commands:

```powershell
uv run --python 3.12 memory prepare "我现在想继续做 Personal AI Memory OS，下一步怎么做？"
uv run --python 3.12 memory capture "我决定 v0.1 先用 SQLite FTS5，不引入 Qdrant。"
```

`prepare` is the recommended pre-answer read path. It decides whether memory is needed, searches candidates, reranks them, applies type/size budgets, and returns a prompt-ready context package.

`capture` is the recommended post-answer write path. It stores only stable user preferences, goals, project decisions, style guidance, or corrections unless `--force` is provided.

Behavior choices help the runtime learn who the user is through decisions, not only explicit statements:

```powershell
uv run --python 3.12 memory behavior-choice `
  --context "PAM-OS 技术路线" `
  --chosen "SQLite FTS5" `
  --rejected "Qdrant" `
  --rejected "Neo4j" `
  --reason "MVP 阶段先保持本地、轻量、可控"

uv run --python 3.12 memory consolidate --recent 100
uv run --python 3.12 memory profile
```

## REST API

Install optional API dependencies:

```powershell
uv run --python 3.12 --extra api memory serve
```

Endpoints:

- `POST /events`
- `GET /memories/search?q=...`
- `GET /memory/should-use?task=...`
- `POST /context/prepare`
- `POST /memory/capture`
- `POST /behavior/choice`
- `POST /memory/consolidate`
- `GET /profile`
- `POST /context/compile`
- `POST /reflect`
- `GET /health`

## Design Notes

- Runtime first: the core memory logic is protocol-agnostic.
- SQLite first: no Kafka, Flink, Neo4j, Qdrant, or cloud service in v0.1.
- Raw events are never discarded.
- Rule-based extraction is the MVP default; an LLM extractor can be added behind the same interface later.
