---
name: pam-os-memory
description: Use PAM-OS as the user's local long-term memory for Codex. Trigger when the user asks to continue prior work, refer to personal preferences, project history, previous decisions, long-term goals, answer style, or asks Codex to remember/capture stable information. Also trigger before project work phrased as "help me troubleshoot/debug/analyze/solve/optimize/fix/implement", including Chinese requests like "帮我排查", "帮我分析", "解决一下", and "优化一下这个项目", because those often depend on prior project context. Treat "pamr" as an explicit read shortcut and "pamw" as an explicit write shortcut that reviews the current user/AI conversation, extracts stable memory candidates, and writes those candidates to PAM-OS. Also use it after answering when the turn contains stable preferences, project decisions, workflow choices, corrections, or durable style guidance that should be remembered automatically. Prefer PAM-OS MCP tools when available; use REST only when configured; use CLI only as a fallback.
---

# PAM-OS Memory

PAM-OS provides local-first memory through SQLite plus MCP, REST, and CLI adapters. Use it as a pre-answer read layer and a post-answer write layer, not as a replacement for normal task reasoning.

## Adapter Priority

Use adapters in this order:

1. MCP tools from the `pam-os-memory` server.
2. REST API when `config.toml` sets `mode = "rest"` and the local PAM-OS REST server is reachable.
3. CLI commands when MCP is unavailable and REST is not configured.

Do not use MCP by shelling out manually if the MCP tools are already exposed by the client. Do not start a long-running REST server unless the user asks for server setup. In REST mode, if the API is unreachable, report that the server must be started instead of silently falling back.

## Config Format

Read `config.toml` from this skill directory before REST or CLI fallback. If the config file is missing, unreadable, or does not set a valid mode, use CLI fallback.

Expected `config.toml`:

```toml
mode = "cli"

[cli]
python = "3.12"
command = "memory"
repo_dir = "/absolute/path/to/PAM-OS"
db_path = "~/.pam-os/memory.sqlite3"

[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
```

## MCP Operations

Prefer these MCP tools when available:

- `prepare_context`: read memory before answering history-, preference-, or project-dependent tasks.
- `capture_memory`: store stable user preferences, goals, project decisions, style guidance, or corrections.
- `record_behavior_choice`: record choices when the user chooses, rejects, or defers options.
- `consolidate_memory`: promote recent evidence into profile traits after meaningful batches.
- `get_profile`: read stable user profile traits when profile context is needed.
- `search_memory`: search stored memories for explicit memory lookup requests.
- `inspect_memory` and `get_storage_stats`: diagnostics only.

When a context package is returned, use `package.content` as private working context. Do not paste the whole package to the user unless asked.

## REST Fallback

REST endpoint equivalents:

- prepare: `POST /context/prepare`
- capture: `POST /memory/capture`
- behavior choice: `POST /behavior/choice`
- consolidate: `POST /memory/consolidate`
- profile: `GET /profile`

If REST `username` and `password` are non-empty, send HTTP Basic Auth on every REST request. If either value is empty, do not send an Authorization header.

## CLI Fallback

CLI fallback is available but may require shell execution approval. In CLI mode, run commands with `uv --directory "<repo_dir>" run ...` and pass `--db "<db_path>"`.

If `[cli].repo_dir` is empty, first locate the PAM-OS repository that contains `pyproject.toml` and `src/pam_os`, then use that absolute path.

```bash
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" prepare "<current task>" --json
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" capture "<stable information>"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" behavior-choice --context "<decision context>" --chosen "<chosen option>"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" consolidate --recent 100
```

## Before Answering

Call `prepare_context` when the user asks about:

- `pamr ...`, which is an explicit manual read shortcut. Call `prepare_context` with `force=true` and use the text after `pamr` as the task when present.
- ongoing projects or "continue where we left off"
- personal preferences, constraints, long-term goals, style, or prior decisions
- "according to my preference", "use my usual style", "remember what I said", "as we discussed", "as mentioned before", "pick up where we left off", or similar history-dependent phrasing
- troubleshooting, debugging, analysis, solving, optimization, fixing, or implementation work in a known project or current repository, including requests like "help me debug this repo", "help me analyze this project", "fix the current codebase", "帮我排查一下...", "帮我分析一下...", "解决一下", and "优化一下这个项目"

Do not read memory for generic one-off factual questions unless the user explicitly requests memory.

## After Answering

When the user writes `pamw`, treat it as an explicit manual write shortcut. Review the current user/AI conversation, extract concise stable memory candidates, and call `capture_memory` for those candidates. The text after `pamw` is only an optional extraction instruction, not the memory content to save verbatim. If no stable preference, project decision, goal, durable style guidance, correction, or workflow choice is present, say that nothing durable was found instead of writing transient chat.

After each substantial user-facing task, quickly check whether the turn contains stable information worth keeping. If yes, call `capture_memory` with a concise normalized candidate rather than the raw conversation. Capture stable information only:

- preferences: "I prefer self-hosted tools"
- goals: "My goal is to build..."
- project decisions: "We decided to use SQLite FTS5", "Do not introduce Qdrant yet"
- style guidance: "Answer more directly next time", "Default to two options before recommending one"
- corrections: "That is not my preference", "I do not want that approach"
- workflow choices: "Use automatic memory capture unless information is ambiguous", "Keep doing this for future debugging tasks"

Skip transient chat, secrets, credentials, medical/legal/financial sensitive details unless the user explicitly asks to store them.

Use `force` only when the user explicitly asks to remember something and the automatic capture gate skips it.

Prefer automatic maintenance over repeated appends: if a similar memory already exists, PAM-OS may reinforce or update it instead of creating a duplicate. For long sessions, send concise candidates such as "用户偏好：PAM-OS 记忆写入应更自动，减少确认打扰。" and let the runtime deduplicate.

## Safety

Keep PAM-OS local by default. Respect `PAM_OS_DB`, `PAM_OS_CONFIG`, and `--db` when present. Never overwrite or delete the user's database unless explicitly instructed.
