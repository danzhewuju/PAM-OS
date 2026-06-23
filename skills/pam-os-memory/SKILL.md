---
name: pam-os-memory
description: Use PAM-OS as the user's local long-term memory for AI assistants and coding agents. Trigger when the user asks to continue prior work, refers to personal preferences, project history, previous decisions, long-term goals, answer style, or asks the assistant to remember/capture stable information. Also trigger before project work phrased as "help me troubleshoot/debug/analyze/solve/optimize/fix/implement", including Chinese requests like "帮我排查", "帮我分析", "解决一下", and "优化一下这个项目", because those often depend on prior project context. Treat "pamr" as an explicit read shortcut and "pamw" as an explicit write shortcut that reviews the current user/assistant conversation, extracts stable memory candidates, and writes those candidates to PAM-OS. Also use it after answering when the turn contains stable preferences, project decisions, workflow choices, corrections, or durable style guidance that should be remembered automatically. Read config.toml first and use either REST or CLI according to mode.
---

# PAM-OS Memory

PAM-OS provides local-first memory through SQLite plus REST and CLI adapters. Use it as a pre-answer read layer and a post-answer write layer, not as a replacement for normal task reasoning.

## Adapter Priority

Read `config.toml` from this skill directory before every PAM-OS operation. Use exactly one adapter according to `mode`:

1. `mode = "rest"`: call the configured REST API.
2. `mode = "cli"`: run CLI commands.
3. Missing, unreadable, or invalid `mode`: use CLI commands.

Use only the CLI or REST adapters described here. Do not start any other local tool server. Do not start a long-running REST server unless the user asks for server setup. In REST mode, if the API is unreachable, report that the server must be started instead of silently falling back to CLI.

## Config Format

If the config file is missing, unreadable, or does not set a valid mode, use CLI.

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

## REST Operations

REST endpoint equivalents:

- add raw event: `POST /events`
- search: `GET /memories/search?q=...&limit=10&type=preference`
- should use memory: `GET /memory/should-use?task=...`
- prepare: `POST /context/prepare`
- capture: `POST /memory/capture`
- behavior choice: `POST /behavior/choice`
- observe turn: `POST /turns/observe`
- consolidate: `POST /memory/consolidate`
- profile: `GET /profile?limit=20&q=...`
- inspect: `GET /memory/inspect?table=all&limit=20&q=...`
- stats: `GET /storage/stats`
- compile: `POST /context/compile`
- reflect: `POST /reflect`
- clear memory: `POST /memory/clear` with `confirm=true`; destructive, user-requested maintenance only.

If REST `username` and `password` are non-empty, send HTTP Basic Auth on every REST request. If either value is empty, do not send an Authorization header.

## CLI Fallback

CLI fallback is available but may require shell execution approval. In CLI mode, run commands with `uv --directory "<repo_dir>" run ...` and pass `--db "<db_path>"`.

If `[cli].repo_dir` is empty, first locate the PAM-OS repository that contains `pyproject.toml` and `src/pam_os`, then use that absolute path.

```bash
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" search "<query>" --limit 10 --type preference
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" should-use "<current task>"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" prepare "<current task>" --json
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" capture "<stable information>"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" behavior-choice --context "<decision context>" --chosen "<chosen option>"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" observe-turn "<user message>" --assistant-message "<assistant response>"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" consolidate --recent 100
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" profile --limit 20
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" inspect --table memories --limit 20 --json
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" stats
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

When the user writes `pamw`, treat it as an explicit manual write shortcut. Review the current user/assistant conversation, extract concise stable memory candidates, and call `capture_memory` for those candidates. The text after `pamw` is only an optional extraction instruction, not the memory content to save verbatim. If no stable preference, project decision, goal, durable style guidance, correction, or workflow choice is present, say that nothing durable was found instead of writing transient chat.

After each substantial user-facing task, call `observe_turn` with the completed user message and assistant response, even when no obvious memory candidate is present. This is the default post-turn path that lets PAM-OS conservatively decide whether to capture stable memories, learn policy signals, or only write an audit trace. A substantial task is any user-facing turn that involved analysis, troubleshooting, implementation, planning, decisions, preferences, corrections, multi-step work, or project context; skip only brief acknowledgements, purely mechanical status updates, and failed turns with no useful answer.

Use this payload shape for the default observation:

```json
{"user_message":"user text","assistant_message":"assistant response","conversation_summary":null,"source_ref":null,"auto_capture":true,"auto_learn_policy":true}
```

Do not replace `observe_turn` with `capture_memory` for normal turns. Use `capture_memory` in addition only when the user explicitly asks to remember/import something or when a concise stable fact is so clear that direct capture is useful. Capture stable information only:

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
