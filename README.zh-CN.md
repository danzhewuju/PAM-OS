<div align="center">
  <h1>PAM-OS</h1>
  <p><strong>个人 AI 记忆操作系统：面向 AI Agent 的本地优先、REST-only 记忆运行时。</strong></p>
  <p>
    <a href="README.md">English</a> ·
    <a href="docs/usage.md">使用文档</a> ·
    <a href="https://github.com/danzhewuju/PAM-OS">GitHub</a>
  </p>
  <p>
    <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache_2.0-blue" /></a>
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB" />
    <img alt="SQLite" src="https://img.shields.io/badge/SQLite-local--first-003B57" />
    <img alt="REST" src="https://img.shields.io/badge/REST-required-009688" />
  </p>
</div>

---

PAM-OS 为 AI 助手提供一个可持久化的个人记忆服务。客户端在任务前后通过 REST 调用它；PAM-OS 负责保存原始事件、提取结构化记忆、检索相关上下文、巩固稳定画像、学习何时使用记忆，并返回可直接注入提示词的上下文包。

```text
AI 客户端 / Skill
  -> PAM-OS REST API (/v1)
  -> PersonalMemoryRuntime
  -> 自适应策略 + Provider 管线
  -> SQLite MemoryStore
  -> 上下文包 / 捕获结果 / 用户画像
```

![PAM-OS 记忆架构](docs/diagrams/memory-architecture.svg)

## 主要特点

- **本地优先**：个人数据保存在用户控制的 SQLite 数据库中。
- **统一 REST 边界**：客户端不再执行本地 PAM-OS 命令。
- **回答前准备上下文**：自动判断是否需要读取记忆并进行预算裁剪。
- **回答后选择性写入**：保存稳定偏好、目标、项目决策、风格和纠正，跳过临时闲聊。
- **用户画像巩固**：重复证据和行为选择可以提升为稳定画像特征。
- **自适应策略记忆**：学习可复用的读取、写入和抑制信号。
- **可替换 Provider**：策略、抽取、检索、重排和巩固仍保持协议无关。

## 快速启动

要求：

- Python 3.11 或更高版本
- 建议使用支持 FTS5 的 SQLite
- 推荐使用 `uv`

安装依赖并启动 REST API：

```bash
uv sync
export PAM_OS_DB="$HOME/.pam-os/memory.sqlite3"
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

检查服务：

```bash
curl http://127.0.0.1:8765/health/live
curl http://127.0.0.1:8765/v1/meta
```

OpenAPI 页面位于 `http://127.0.0.1:8765/docs`。

## 推荐 Agent 工作流

回答依赖历史的任务前准备上下文：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/context/prepare \
  -H 'Content-Type: application/json' \
  -d '{"task":"按我的偏好规划 PAM-OS 下一步。","force":false}'
```

完成重要回答后观察整个轮次：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/turns/observe \
  -H 'Content-Type: application/json' \
  -d '{"user_message":"我偏好本地优先系统。","assistant_message":"收到。","auto_capture":true,"auto_learn_policy":true}'
```

用户明确要求记住或导入内容时直接捕获：

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/memory/capture \
  -H 'Content-Type: application/json' \
  -d '{"content":"用户偏好本地优先、轻量、可控的技术方案。","source":"assistant","force":true}'
```

## Plugin 与 Skill

`pam-os-memory` skill 负责告诉 Codex、Claude Code、OpenCode 和 Hermes 什么时候读取、写入和观察记忆。配置文件只保留 REST 参数：

```toml
[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
timeout_seconds = 10
```

远程安装：

```bash
curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/install-plugin.sh | bash
```

从当前 checkout 安装：

```bash
scripts/install-plugin-local.sh
```

Windows PowerShell：

```powershell
.\scripts\install-plugin-local.ps1
```

安装器会优先读取已有 skill 的 REST URL、用户名、密码和超时配置，并把它们作为默认值。交互安装会展示旧 URL 和用户名，密码只显示“已配置/未配置”，直接回车即可沿用；命令行参数和 `PAM_OS_REST_*` 环境变量优先级更高。安装器会在支持的平台上限制凭据配置文件权限。远程服务必须使用 HTTPS，并避免把密码直接写进 shell 历史。

## REST API

正式接口统一使用 `/v1`。v0.3 的无版本路径暂时作为隐藏兼容别名保留一个迁移窗口。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health/live` | 公开存活检查。 |
| `GET` | `/v1/health/ready` | 认证后的数据库就绪检查。 |
| `GET` | `/v1/meta` | 运行时与 API 版本。 |
| `POST` | `/v1/events` | 写入原始事件并按需抽取记忆。 |
| `POST` | `/v1/memories/search` | 按类型和分数条件搜索记忆。 |
| `POST` | `/v1/memory/should-use` | 判断任务是否需要使用记忆。 |
| `POST` | `/v1/context/prepare` | 准备可注入提示词的上下文。 |
| `POST` | `/v1/memory/capture` | 选择性捕获稳定记忆。 |
| `POST` | `/v1/behavior/choice` | 记录行为选择证据。 |
| `POST` | `/v1/turns/observe` | 观察一个完整对话轮次。 |
| `POST` | `/v1/memory/consolidate` | 将证据巩固为画像。 |
| `GET` | `/v1/profile` | 读取画像特征。 |
| `POST` | `/v1/context/compile` | 直接检索并编译上下文。 |
| `POST` | `/v1/reflect` | 从近期记忆构建反思上下文。 |
| `GET` | `/v1/storage/stats` | 查看存储统计。 |
| `GET` | `/v1/memory/inspect` | 查看记忆表和质量轨迹。 |
| `POST` | `/v1/memory/clear` | 显式确认后清空全部记忆。 |

请求模型会拒绝未知字段和超大请求体，并限制文本长度、分数范围和结果条数。参数校验和运行时/存储错误会返回结构化错误。

## 安全模型

PAM-OS v0.4 回归为个人、单数据库服务。旧版允许客户端自行传 `user_id` 切换 SQLite 文件，但这不是真正的鉴权边界，因此已经移除。

在 `config/pam-os.toml` 开启 Basic Auth：

```toml
[server]
host = "127.0.0.1"
port = 8765
auth_enabled = true
auth_username = "user"
auth_password = "change-me"
```

也可以使用环境变量：

```bash
export PAM_OS_AUTH_ENABLED=true
export PAM_OS_AUTH_USERNAME=user
export PAM_OS_AUTH_PASSWORD=change-me
```

服务只要离开 localhost，就必须通过 HTTPS、TLS 反向代理或可信私网访问。不要在公网明文 HTTP 上传输 Basic Auth 凭据。

## SQLite 并发基础

REST 服务使用短连接访问 SQLite，开启外键、busy timeout，并在初始化时启用 WAL。这个配置适合个人 Agent 的常规并发，同时保持部署轻量。

## Docker

```bash
docker build -t pam-os .
docker volume create pam-os-data
docker run -d --name pam-os \
  -p 8765:8765 \
  -v pam-os-data:/data \
  -e PAM_OS_AUTH_ENABLED=true \
  -e PAM_OS_AUTH_USERNAME=user \
  -e PAM_OS_AUTH_PASSWORD=change-me \
  pam-os
```

容器直接启动 ASGI factory，数据库位于 `/data/memory.sqlite3`。

## 配置

```bash
cp config/pam-os.example.toml config/pam-os.toml
```

优先级为：环境变量 > `config/pam-os.toml` > 内置默认值。

```bash
export PAM_OS_DB="$HOME/.pam-os/memory.sqlite3"
export PAM_OS_CONFIG="/path/to/pam-os.toml"
export PAM_OS_HOST="0.0.0.0"
export PAM_OS_PORT="8765"
```

完整配置见 [config/pam-os.example.toml](config/pam-os.example.toml)。

## 项目结构

```text
src/pam_os/
  api.py             # REST API、请求校验、认证、健康检查、错误处理
  runtime.py         # 协议无关的记忆运行时
  store.py           # SQLite schema、写入、检索和诊断
  orchestrator.py    # 策略、检索、重排和上下文预算
  providers.py       # 可替换 Provider 接口
  adaptive_policy.py # 学习信号与规则 fallback
  rule_provider.py   # 默认本地 Provider
  extractor.py       # 规则抽取器
  context.py         # 上下文编译器
```

## 开发

```bash
uv sync --extra dev
uv run pytest
```

质量评估保留为 Python 开发接口 `pam_os.quality.evaluate_quality_cases`，不再作为产品命令暴露。

## 更新

通过 `GET /v1/meta` 查看运行版本，然后更新托管 checkout 并重装集成：

```bash
curl -fsSL https://raw.githubusercontent.com/danzhewuju/PAM-OS/refs/heads/master/scripts/update.sh | bash
```

## License

PAM-OS 使用 [Apache License 2.0](LICENSE)。
