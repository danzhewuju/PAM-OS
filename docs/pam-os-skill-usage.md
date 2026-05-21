# PAM-OS Skill 使用指南

这份文档说明如何让大模型通过 PAM-OS skill 使用本地长期记忆，并用 skill 自带的配置文件在 CLI 和 REST API 之间切换。

## 1. 核心策略

PAM-OS skill 不再默认依赖环境变量来选择模式，也不默认走 MCP。

当前策略是：

```text
默认：CLI
特殊配置：REST API
```

大模型使用 skill 时，先读取 skill 目录里的 `config.toml`：

```text
Codex:      .agents/skills/pam-os-memory/config.toml
Claude:     .claude/skills/pam-os-memory/config.toml
```

如果配置文件不存在、读不到，或 `mode` 不是有效值，就使用 CLI 模式。

## 2. 配置文件

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
| `[rest].url` | REST server 地址，默认 `http://127.0.0.1:8765`。 |
| `[rest].username` | REST Basic Auth 用户名。空字符串表示不发送认证。 |
| `[rest].password` | REST Basic Auth 密码。空字符串表示不发送认证。 |
| `[cli].python` | CLI 模式使用的 Python 版本。 |
| `[cli].command` | CLI 入口命令，默认 `memory`。 |
| `[cli].repo_dir` | PAM-OS 仓库绝对路径。CLI 模式会在这个目录下运行 `uv`。 |
| `[cli].db_path` | SQLite 数据库路径，默认 `~/.pam-os/memory.sqlite3`，多终端共用。 |

## 3. CLI 模式

CLI 是默认模式，不需要启动常驻服务。

确认配置：

```toml
mode = "cli"
```

大模型会使用类似命令：

```powershell
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" prepare "按我的偏好，下一步怎么做？" --json
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" capture "我偏好本地优先、轻量、可控的技术方案。"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" behavior-choice --context "技术路线" --chosen "SQLite FTS5" --rejected "Qdrant"
uv --directory "<repo_dir>" run --python 3.12 memory --db "<db_path>" consolidate --recent 100
```

CLI 模式适合日常开发和最小可用场景。

## 4. REST 模式

REST 模式适合你希望大模型直接通过 HTTP API 使用 PAM-OS 的场景。

### 4.1 修改 skill 配置

把对应客户端的 `config.toml` 改成：

```toml
mode = "rest"

[cli]
python = "3.12"
command = "memory"
repo_dir = "/absolute/path/to/PAM-OS"
db_path = "~/.pam-os/memory.sqlite3"

[rest]
url = "http://127.0.0.1:8765"
username = "yuhao"
password = "change-me"
```

Codex 改这里：

```text
.agents/skills/pam-os-memory/config.toml
```

Claude Code 改这里：

```text
.claude/skills/pam-os-memory/config.toml
```

### 4.2 启动 REST server

REST 模式需要你先启动 PAM-OS REST 服务：

```powershell
cd C:\project\PAM-OS

$env:PAM_OS_DB = "$HOME\.pam-os\memory.sqlite3"
$env:PAM_OS_CONFIG = "C:\project\PAM-OS\config\pam-os.toml"

uv run --python 3.12 --extra api memory serve --host 127.0.0.1 --port 8765
```

skill 不会自动启动长驻服务。如果大模型发现 REST 不通，它应该提示你先启动 server。

### 4.3 开启 REST 用户名密码认证

服务端认证在 `config/pam-os.toml` 中配置：

```toml
[server]
host = "127.0.0.1"
port = 8765
auth_enabled = true
auth_username = "yuhao"
auth_password = "change-me"
```

也可以用环境变量覆盖，避免把真实密码写进仓库文件：

```powershell
$env:PAM_OS_AUTH_ENABLED = "true"
$env:PAM_OS_AUTH_USERNAME = "yuhao"
$env:PAM_OS_AUTH_PASSWORD = "change-me"
```

客户端认证在 skill 的 `config.toml` 中配置：

```toml
[rest]
url = "http://127.0.0.1:8765"
username = "yuhao"
password = "change-me"
```

如果 `username` 或 `password` 为空，大模型不会发送 `Authorization` header。

### 4.4 验证 REST server

另开一个终端：

```powershell
curl http://127.0.0.1:8765/health
```

看到 `ok: true` 就说明可用。

如果开启了认证：

```powershell
curl -u yuhao:change-me http://127.0.0.1:8765/health
```

### 4.5 REST 调用示例

准备上下文：

```powershell
$pair = "yuhao:change-me"
$token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/context/prepare" `
  -Method Post `
  -Headers @{ Authorization = "Basic $token" } `
  -ContentType "application/json" `
  -Body '{"task":"按我的偏好，PAM-OS 下一步怎么做？","force":false,"limit":8,"max_chars":3000}'
```

捕获记忆：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/memory/capture" `
  -Method Post `
  -Headers @{ Authorization = "Basic $token" } `
  -ContentType "application/json" `
  -Body '{"content":"我偏好本地优先、轻量、可控的技术方案。","force":true}'
```

记录行为选择：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/behavior/choice" `
  -Method Post `
  -Headers @{ Authorization = "Basic $token" } `
  -ContentType "application/json" `
  -Body '{"context":"PAM-OS 技术路线","chosen":["REST API"],"rejected":["MCP-first"],"reason":"希望大模型直接通过 REST 使用 PAM-OS"}'
```

## 5. 在 Codex 中使用

Codex 的 skill 路径：

```text
.agents/skills/pam-os-memory/SKILL.md
```

默认 CLI 使用：

```text
Use $pam-os-memory. 按我的偏好，继续规划 PAM-OS 下一步。
```

如果要让大模型直接走 REST：

1. 修改 `.agents/skills/pam-os-memory/config.toml`，设置 `mode = "rest"`。
2. 启动 REST server。
3. 重启 Codex 会话，让 skill 重新加载。
4. 正常使用 `$pam-os-memory`。

不需要再设置 `PAM_OS_MODE` 或 `PAM_OS_URL` 给 Codex。模式由 skill 配置文件决定。

## 6. 在 Claude Code 中使用

Claude Code 的 skill 路径：

```text
.claude/skills/pam-os-memory/SKILL.md
```

如果要让 Claude Code 走 REST：

1. 修改 `.claude/skills/pam-os-memory/config.toml`，设置 `mode = "rest"`。
2. 启动 REST server。
3. 重启 Claude Code 会话。
4. 正常使用 `$pam-os-memory`。

## 7. 切换回 CLI

把对应 skill 配置改回：

```toml
mode = "cli"
```

然后重启 AI 客户端会话。

CLI 模式不需要 REST server。

## 8. 接入验证

先写入一条测试记忆：

```powershell
uv run --python 3.12 memory capture "我偏好本地优先、轻量、可控的技术方案。" --force
```

然后在 Codex 或 Claude Code 中问：

```text
Use $pam-os-memory. 按我的偏好，PAM-OS 下一步应该怎么做？
```

如果 `mode = "cli"`，大模型应该使用本地 CLI 命令。

如果 `mode = "rest"`，大模型应该读取 `[rest].url`，然后调用 REST API。

## 9. 推荐用法

日常开发：

```toml
mode = "cli"
```

希望大模型直接通过 HTTP 使用 PAM-OS：

```toml
mode = "rest"
```

保留 MCP 作为可选集成，不作为 skill 默认路径。
