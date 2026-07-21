# PAM-OS Skill 使用指南

PAM-OS skill 只通过 REST API 访问记忆服务。

## 安装

```bash
./scripts/install.sh
```

安装器再次运行时会自动识别已有目标并执行更新。本地开发可直接指定当前 checkout：

```bash
./scripts/install.sh --repo-dir "$PWD" --yes
```

Windows：

```powershell
.\scripts\install.ps1 --repo-dir $PWD --yes
```

支持 Codex、Claude Code、OpenCode 和 Hermes。安装器会复制 skill、写入 REST 配置，并清理它管理过的旧本地工具注册。重装时会读取已有 skill 配置并默认沿用 URL、Bearer Token 和超时；Token 只显示配置状态，不会明文回显。

## 配置

```toml
[versions]
skill = "0.5.2"
api = "v2"
server = "0.5.2"
server_api = "v2"
server_checked_at = "2026-07-18T00:00:00Z"
status = "match"

[rest]
url = "http://127.0.0.1:8765"
token = ""
timeout_seconds = 10
```

配置路径示例：

```text
Codex:  ~/.codex/skills/pam-os-memory/config.toml
Claude: ~/.claude/skills/pam-os-memory/config.toml
Hermes: ~/.hermes/skills/pam-os-memory/config.toml
```

配置不存在、URL 为空或服务不可达时，skill 应提示用户配置或启动 REST 服务，不执行本地 fallback。

## 启动服务

```bash
uv sync
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

```bash
curl http://127.0.0.1:8765/health/live
```

## 认证

服务端首次启动时设置 Bootstrap Token，并通过 `/v2/admin/users` 创建用户及 API Key：

```toml
[server]
bootstrap_token = "replace-with-a-long-random-secret"
```

skill 的 `[rest].token` 中配置用户 API Key。Token 固定绑定用户，业务请求不发送 `user_id`。非 localhost 服务必须使用 HTTPS。

大模型不得读取或打印 `config.toml`，也不得自行拼接 `curl`、`Invoke-RestMethod` 或 `Authorization` 请求。所有运行时调用都必须通过 skill 内置的安全客户端；PowerShell 使用 `scripts/pam_client.ps1`，Bash 使用 `scripts/pam_client.sh`，二者会启动 `pam_client.py`。客户端在进程内加载 Token，并对输出和错误做脱敏。安装时也不要把 Token 放进命令参数，使用交互式安全输入、已有配置、`PAM_OS_REST_TOKEN` 安全环境注入，或 `--rest-token-file`。

## 调用策略

- 回答前：历史相关任务调用 `POST /v2/context/prepare`。
- 回答后：重要轮次调用 `POST /v2/turns/observe`。
- 显式记住：调用 `POST /v2/memory/capture`。
- 用户选择方案：调用 `POST /v2/behavior/choice`。
- `pamr`：prepare 时设置 `force=true`。
- `pamw`：从当前对话提取稳定候选后 capture。

不要保存短暂闲聊、凭据、秘密或未经用户要求的敏感信息。不要在没有明确授权时调用 `/v2/memory/clear`。

## 验证

先通过 skill 的安全客户端写入一条偏好：

```bash
scripts/pam_client.sh request POST /v2/memory/capture \
  --body-json '{"content":"我偏好本地优先、轻量、可控的技术方案。","force":true}'
```

然后在客户端中询问：

```text
Use $pam-os-memory. 按我的偏好，PAM-OS 下一步应该怎么做？
```
