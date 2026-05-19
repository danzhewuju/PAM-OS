# Personal AI Memory OS MVP

This repository implements the first executable slice of `Personal Memory Runtime`:

```text
Raw Event -> Memory Extraction -> SQLite Memory Store -> Retrieval -> Context Compilation
```

The MVP is local-first and deliberately small. The runtime stores raw events forever, extracts structured memories, retrieves them with SQLite FTS5 when available, and compiles a prompt-ready context package.

## Quick Start

```powershell
uv run --python 3.12 memory init
uv run --python 3.12 memory add "我今天在思考 Personal AI Memory OS，倾向先做本地 MCP Server，不想一开始引入重型组件。"
uv run --python 3.12 memory search "Personal AI Memory OS 下一步实现"
uv run --python 3.12 memory compile "我现在想继续做 Personal AI Memory OS，下一步怎么做？"
```

By default, data is stored in `.pam-os/memory.sqlite3`. Override it with:

```powershell
$env:PAM_OS_DB = "C:\path\to\memory.sqlite3"
```

## CLI

```text
memory init
memory add <content> [--source manual] [--metadata-json {...}]
memory search <query> [--limit 10]
memory compile <task> [--limit 12]
memory reflect [--recent 50]
memory serve [--host 127.0.0.1] [--port 8765]
memory mcp
```

## REST API

Install optional API dependencies:

```powershell
uv run --python 3.12 --extra api memory serve
```

Endpoints:

- `POST /events`
- `GET /memories/search?q=...`
- `POST /context/compile`
- `POST /reflect`
- `GET /health`

## MCP Adapter

Install optional MCP dependencies:

```powershell
uv run --python 3.12 --extra mcp memory mcp
```

MCP tools:

- `remember`
- `search_memory`
- `compile_context`
- `reflect`

## Design Notes

- Runtime first, MCP second: the core memory logic is protocol-agnostic.
- SQLite first: no Kafka, Flink, Neo4j, Qdrant, or cloud service in v0.1.
- Raw events are never discarded.
- Rule-based extraction is the MVP default; an LLM extractor can be added behind the same interface later.
