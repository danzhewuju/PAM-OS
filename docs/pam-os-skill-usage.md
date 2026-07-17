# PAM-OS Skill 使用指南

PAM-OS skill 只通过 REST API 访问记忆服务。

## 安装

```bash
./scripts/install-plugin.sh
```

本地开发：

```bash
./scripts/install-plugin-local.sh
```

Windows：

```powershell
.\scripts\install-plugin-local.ps1
```

支持 Codex、Claude Code、OpenCode 和 Hermes。安装器会复制 skill、写入 REST 配置，并清理它管理过的旧本地工具注册。重装时会读取已有 skill 配置并默认沿用 URL、用户名、密码和超时；密码只显示配置状态，不会明文回显。

## 配置

```toml
[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
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

服务端：

```toml
[server]
auth_enabled = true
auth_username = "user"
auth_password = "change-me"
```

skill 的 `[rest]` 中配置同一组凭据。非 localhost 服务必须使用 HTTPS。

## 调用策略

- 回答前：历史相关任务调用 `POST /v1/context/prepare`。
- 回答后：重要轮次调用 `POST /v1/turns/observe`。
- 显式记住：调用 `POST /v1/memory/capture`。
- 用户选择方案：调用 `POST /v1/behavior/choice`。
- `pamr`：prepare 时设置 `force=true`。
- `pamw`：从当前对话提取稳定候选后 capture。

不要保存短暂闲聊、凭据、秘密或未经用户要求的敏感信息。不要在没有明确授权时调用 `/v1/memory/clear`。

## 验证

先通过 REST 写入一条偏好：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/memory/capture \
  -H 'Content-Type: application/json' \
  -d '{"content":"我偏好本地优先、轻量、可控的技术方案。","force":true}'
```

然后在客户端中询问：

```text
Use $pam-os-memory. 按我的偏好，PAM-OS 下一步应该怎么做？
```
