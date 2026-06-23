# PAM-OS Skill 使用指南

PAM-OS 现在只支持两种执行方式：

- `mode = "cli"`：通过本地 `memory` CLI 调用 PAM-OS。
- `mode = "rest"`：通过运行中的 PAM-OS REST API 调用。

skill 负责判断什么时候读写记忆；`config.toml` 负责决定实际调用 CLI 还是 REST。

## 1. 安装

推荐通过安装器安装多端 skill：

```bash
./scripts/install-plugin.sh
```

本地开发时使用当前 checkout：

```bash
./scripts/install-plugin-local.sh
```

Windows PowerShell：

```powershell
.\scripts\install-plugin-local.ps1
```

Codex 目标会写入：

- `~/.local/share/pam-os/repo`：默认托管运行仓库。
- `~/plugins/pam-os-memory`：Codex plugin 源目录。
- `~/.agents/plugins/marketplace.json`：Codex 个人 marketplace 入口。
- `~/.codex/skills/pam-os-memory`：Codex global skill。

其他目标会写入：

- Claude Code：`~/.claude/skills/pam-os-memory`
- OpenCode：`~/.config/opencode/AGENTS.md`，并复用 Claude-compatible skill
- Hermes：`~/.hermes/skills/pam-os-memory` 和 `~/.hermes/AGENTS.md`

安装器会写入 skill `config.toml`，并清理它管理过的旧本地工具注册。

## 2. 配置文件

每个客户端 skill 目录都有自己的 `config.toml`：

```text
Codex:      ~/.codex/skills/pam-os-memory/config.toml
Claude:     ~/.claude/skills/pam-os-memory/config.toml
Hermes:     ~/.hermes/skills/pam-os-memory/config.toml
```

默认配置：

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

字段说明：

| 字段 | 说明 |
| --- | --- |
| `mode = "cli"` | 默认模式。大模型通过本地命令调用 PAM-OS。 |
| `mode = "rest"` | REST 模式。大模型通过 HTTP API 调用 PAM-OS。 |
| `[cli].python` | CLI 模式使用的 Python 版本。 |
| `[cli].command` | CLI 入口命令，默认 `memory`。 |
| `[cli].repo_dir` | PAM-OS 仓库绝对路径。 |
| `[cli].db_path` | SQLite 数据库路径，默认 `~/.pam-os/memory.sqlite3`。 |
| `[rest].url` | REST server 地址，默认 `http://127.0.0.1:8765`。 |
| `[rest].username` | REST Basic Auth 用户名。空字符串表示不发送认证。 |
| `[rest].password` | REST Basic Auth 密码。空字符串表示不发送认证。 |

如果配置文件不存在、读不到，或 `mode` 不是 `cli` / `rest`，skill 使用 CLI 模式。

## 3. CLI 模式

CLI 模式不需要启动常驻服务：

```toml
mode = "cli"
```

常用命令：

```powershell
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" prepare "按我的偏好，下一步怎么做？" --json
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" observe-turn "<user message>" --assistant-message "<assistant response>"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" capture "我偏好本地优先、轻量、可控的技术方案。"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" behavior-choice --context "技术路线" --chosen "SQLite FTS5" --rejected "Qdrant"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" consolidate --recent 100
```

## 4. REST 模式

REST 模式适合你希望大模型通过 HTTP API 使用 PAM-OS 的场景：

```toml
mode = "rest"

[rest]
url = "http://127.0.0.1:8765"
username = "yuhao"
password = "change-me"
```

启动 REST server：

```powershell
cd C:\project\PAM-OS
$env:PAM_OS_DB = "$HOME\.pam-os\memory.sqlite3"
uv run --python 3.12 --extra api memory serve --host 127.0.0.1 --port 8765
```

skill 不会自动启动长驻服务。如果 REST 不通，它应该提示你先启动 server，而不是自动切到 CLI。

服务端认证在 `config/pam-os.toml` 中配置：

```toml
[server]
host = "127.0.0.1"
port = 8765
auth_enabled = true
auth_username = "yuhao"
auth_password = "change-me"
```

也可以用环境变量覆盖：

```powershell
$env:PAM_OS_AUTH_ENABLED = "true"
$env:PAM_OS_AUTH_USERNAME = "yuhao"
$env:PAM_OS_AUTH_PASSWORD = "change-me"
```

健康检查：

```powershell
curl http://127.0.0.1:8765/health
```

REST 调用示例：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/context/prepare" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"task":"按我的偏好，PAM-OS 下一步怎么做？","force":false,"limit":8,"max_chars":3000}'
```

## 5. 使用策略

回答前，当用户请求依赖历史、偏好、项目上下文、长期目标、回答风格或先前决策时，调用 PAM-OS 准备上下文。

回答后，对 substantial user-facing turn 调用 `observe-turn` / `POST /turns/observe`，让 PAM-OS 保守决定是否捕获稳定偏好、项目决策、长期目标、纠正或策略信号。

显式读写快捷方式：

- `pamr ...`：强制读取相关记忆。
- `pamw ...`：从当前对话中提取稳定信息并写入记忆。

跳过短暂闲聊、临时状态、失败且没有有用结果的 turn，以及未经用户明确要求的敏感信息。

## 6. 验证

先写入一条测试记忆：

```powershell
uv run --python 3.12 memory capture "我偏好本地优先、轻量、可控的技术方案。" --force
```

然后在 Codex 或 Claude Code 中问：

```text
Use $pam-os-memory. 按我的偏好，PAM-OS 下一步应该怎么做？
```

CLI 模式下，skill 应读取配置并运行本地 `memory` 命令。REST 模式下，skill 应读取 `[rest].url` 并调用 REST API。
