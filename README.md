# PAM-OS

Personal AI Memory OS: a local-first memory runtime for AI agents.

PAM-OS gives assistants a durable memory layer they can call before and after a task. It stores raw events, extracts structured memories, retrieves relevant context, consolidates stable profile traits, and returns prompt-ready context packages through CLI, MCP, or REST.

```text
Raw Events -> Memory Extraction -> SQLite Store -> Retrieval -> Context Package
                                      |
                                      v
                         Behavior Evidence -> Profile Traits
```

[![PAM-OS memory architecture](docs/diagrams/memory-architecture.svg)](docs/diagrams/memory-architecture.svg)

## Why PAM-OS?

Most AI tools are stateless unless each client builds its own memory system. PAM-OS is a small runtime that keeps memory outside the model and outside any single chat client.

- **Local-first**: data lives in SQLite at `~/.pam-os/memory.sqlite3` by default.
- **Agent-ready**: use it from Codex through the packaged plugin, MCP tools, or the skill fallback.
- **Prompt-ready retrieval**: `prepare` decides whether memory is needed, retrieves memories, applies budgets, and emits context text.
- **Selective capture**: `capture` stores stable preferences, goals, project decisions, style guidance, and corrections while skipping transient chat.
- **Profile consolidation**: behavior choices and repeated evidence can be promoted into stable user traits.
- **Protocol-agnostic core**: the same runtime backs CLI, REST API, and MCP.
- **No external service required**: the core runtime uses Python and SQLite.

## Install

Requirements:

- Python 3.11 or newer
- `uv` recommended for local execution
- SQLite with FTS5 when available

Initialize the runtime from a checkout:

```bash
uv run --python 3.12 memory init
```

PAM-OS supports two integration packages.

### Skill-only

Use this when your client supports Skills or project instructions, but does not need plugin discovery or MCP tool registration. The installer downloads and installs the `pam-os-memory` skill, then configures it to call the local PAM-OS runtime through CLI by default.

```bash
curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/install-skill.sh | bash
```

### Plugin + MCP

Use this for Codex, Claude Code, OpenCode, or Hermes integration. The installer maintains a managed PAM-OS checkout at `~/.local/share/pam-os/repo`, installs the selected client integration, and points MCP-capable clients at the same checkout so plugin, skill, and runtime versions stay aligned.

```bash
./scripts/install-plugin.sh
```

The plugin installer writes:

- `~/.local/share/pam-os/repo`, refreshed from the configured Git ref by default
- Codex: `~/plugins/pam-os-memory`, `~/.agents/plugins/marketplace.json`, `~/.codex/skills/pam-os-memory`, and `~/.codex/config.toml`
- Claude Code: `~/.claude/skills/pam-os-memory`
- OpenCode: `~/.config/opencode/AGENTS.md` plus the Claude-compatible skill
- Hermes: `~/.hermes/config.yaml` and `~/.hermes/AGENTS.md`

For local development, pass `--repo-dir /path/to/PAM-OS` or `--source /path/to/plugins/pam-os-memory`. For non-interactive Codex installs, run `./scripts/install-plugin.sh --codex --yes`. Restart the selected client after installation. The skill policy decides when to capture memory; it records stable preferences, project decisions, goals, and corrections, not every chat turn.

## Quick Start

Initialize the local memory database:

```bash
uv run --python 3.12 memory init
```

Capture a stable project decision:

```bash
uv run --python 3.12 memory capture "I decided PAM-OS v0.1 should use SQLite FTS5 before adding a vector database." --force
```

Prepare context for a new task:

```bash
uv run --python 3.12 memory prepare "Continue PAM-OS and suggest the next implementation step."
```

Search stored memories:

```bash
uv run --python 3.12 memory search "PAM-OS SQLite FTS5"
```

Inspect storage:

```bash
uv run --python 3.12 memory stats
uv run --python 3.12 memory inspect --limit 10
```

## Core Concepts

| Concept | Meaning |
| --- | --- |
| Event | The raw input record from a conversation, tool, import, or API call. |
| Memory | Structured long-term information extracted from an event. |
| Behavior event | A user choice, rejection, or deferral recorded as behavioral evidence. |
| Profile evidence | Intermediate evidence used to support a profile trait. |
| Profile trait | A more stable description of user preferences, style, goals, or decision patterns. |
| Context package | Prompt-ready text compiled for a specific task. |

Memory types include `preference`, `goal`, `project`, `style`, `episodic`, and `semantic`.

## Recommended Agent Workflow

Use `prepare` before answering when the task depends on user preferences, prior decisions, ongoing projects, long-term goals, answer style, or earlier conversation history:

```bash
uv run --python 3.12 memory prepare "Plan the next PAM-OS milestone based on my preferences." --json
```

Use `capture` after answering when the conversation contains stable information worth keeping:

```bash
uv run --python 3.12 memory capture "The user prefers local-first, lightweight, controllable technical designs."
```

Record choices when the user picks one option over another:

```bash
uv run --python 3.12 memory behavior-choice \
  --context "PAM-OS storage roadmap" \
  --chosen "SQLite FTS5" \
  --rejected "Qdrant" \
  --reason "Keep the MVP local and lightweight."
```

Consolidate recent evidence into profile traits:

```bash
uv run --python 3.12 memory consolidate --recent 100
uv run --python 3.12 memory profile
```

## Codex Plugin and MCP

The repository includes a Codex plugin package:

```text
plugins/pam-os-memory/
  .codex-plugin/plugin.json
  .mcp.json
  skills/pam-os-memory/SKILL.md
```

The recommended integration is:

```text
Codex Plugin
  |-- MCP server registration  # tool execution
  `-- pam-os-memory skill      # memory usage policy
```

Available MCP tools:

- `prepare_context`
- `capture_memory`
- `record_behavior_choice`
- `consolidate_memory`
- `get_profile`
- `search_memory`
- `inspect_memory`
- `get_storage_stats`

You can also run the MCP server directly:

```bash
uv run --python 3.12 pam-os-mcp --db ~/.pam-os/memory.sqlite3
```

or through the `memory` CLI:

```bash
uv run --python 3.12 memory --db ~/.pam-os/memory.sqlite3 mcp
```

## CLI Reference

```text
memory init
memory add <content> [--source manual] [--metadata-json {...}]
memory search <query> [--limit 10] [--type project]
memory should-use <task>
memory prepare <task> [--conversation-summary ...] [--force] [--limit 12] [--max-chars 4000] [--json]
memory capture <content> [--source conversation] [--metadata-json {...}] [--force]
memory behavior-choice --context <context> --chosen <option> [--rejected <option>] [--deferred <option>]
memory consolidate [--recent 100]
memory profile [--limit 20] [--query <query>]
memory compile <task> [--limit 12]
memory reflect [--recent 50]
memory stats
memory inspect [--table all] [--limit 20] [--query <query>] [--json]
memory serve [--host 127.0.0.1] [--port 8765]
memory mcp
```

Global options go before the subcommand:

```bash
uv run --python 3.12 memory --db ~/.pam-os/memory.sqlite3 stats
uv run --python 3.12 memory --config config/pam-os.toml prepare "Continue PAM-OS"
```

## REST API

Install optional API dependencies and start the server:

```bash
uv run --python 3.12 --extra api memory serve --host 127.0.0.1 --port 8765
```

Health check:

```bash
curl http://127.0.0.1:8765/health
```

Core endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health, database path, and FTS status. |
| `GET` | `/storage/stats` | Storage statistics. |
| `GET` | `/memory/inspect` | Inspect tables and diagnostic rows. |
| `POST` | `/events` | Add a raw event and optionally extract memories. |
| `GET` | `/memories/search?q=...` | Search memories. |
| `GET` | `/memory/should-use?task=...` | Decide whether a task should use memory. |
| `POST` | `/context/prepare` | Prepare prompt-ready memory context. |
| `POST` | `/memory/capture` | Selectively capture stable memory. |
| `POST` | `/behavior/choice` | Record a choice as behavior evidence. |
| `POST` | `/memory/consolidate` | Consolidate memories and behavior into profile traits. |
| `GET` | `/profile` | Read profile traits. |
| `POST` | `/context/compile` | Compile context directly from search results. |
| `POST` | `/reflect` | Summarize recent memories as context. |
| `POST` | `/memory/clear` | Clear all memory data with confirmation. |

## Configuration

Copy the example config:

```bash
cp config/pam-os.example.toml config/pam-os.toml
```

Configuration precedence:

```text
CLI arguments > environment variables > config/pam-os.toml > built-in defaults
```

Common environment variables:

```bash
export PAM_OS_DB="$HOME/.pam-os/memory.sqlite3"
export PAM_OS_CONFIG="/path/to/pam-os.toml"
export PAM_OS_AUTH_ENABLED="true"
export PAM_OS_AUTH_USERNAME="user"
export PAM_OS_AUTH_PASSWORD="change-me"
```

Important config sections:

| Section | Purpose |
| --- | --- |
| `[storage]` | SQLite database path. |
| `[server]` | REST host, port, and optional Basic Auth. |
| `[context]` | Memory count, context character budget, and profile injection limit. |
| `[consolidation]` | Evidence scan window and profile stability growth settings. |
| `[orchestrator]` | Read/capture thresholds and candidate expansion. |
| `[retrieval]` | Query term extraction settings. |
| `[profile]` | Default profile query limit. |

See [config/pam-os.example.toml](config/pam-os.example.toml) for the full template.

## Project Structure

```text
PAM-OS/
  src/pam_os/
    runtime.py        # protocol-agnostic memory runtime
    store.py          # SQLite schema, writes, retrieval, inspection
    extractor.py      # rule-based MVP extractor
    orchestrator.py   # memory read/capture decisions, reranking, budgets
    context.py        # prompt-ready context compiler
    consolidator.py   # behavior/profile consolidation
    cli.py            # memory CLI
    api.py            # REST API
    mcp.py            # MCP stdio server
  plugins/
    pam-os-memory/    # Codex plugin package
  skills/
    pam-os-memory/    # standalone skill package
  docs/
    usage.md          # full usage guide
    design/           # design notes
  tests/
```

## Development

Run tests:

```bash
uv run --python 3.12 --extra dev pytest
```

Run a focused diagnostic check:

```bash
uv run --python 3.12 memory stats
uv run --python 3.12 memory inspect --limit 20
```

## Roadmap

PAM-OS is intentionally small today. The current runtime is the executable foundation for a larger personal memory layer:

- richer extraction behind the existing extractor interface
- better consolidation and contradiction handling
- broader MCP/client packaging
- import/export and migration tools
- stronger diagnostics for memory quality and retrieval behavior

## Documentation

- [Usage guide](docs/usage.md)
- [Skill and plugin guide](docs/pam-os-skill-usage.md)
- [Profile memory design](docs/design/people-understanding-profile-memory.md)
