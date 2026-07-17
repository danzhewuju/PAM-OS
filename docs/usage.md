# PAM-OS 使用文档

PAM-OS v0.4 将 REST API 设为唯一产品入口。核心 `PersonalMemoryRuntime` 仍保持协议无关，但 AI 客户端、skill、插件和部署都通过 `/v1` HTTP 接口访问，不再提供本地业务命令。

## 1. 架构

```text
Agent / Skill
  -> REST API
     -> 请求校验 / Basic Auth / 错误映射
     -> PersonalMemoryRuntime
        -> AdaptiveMemoryPolicy
        -> Extraction / Retrieval / Reranking
        -> Profile Consolidation
        -> Context Compiler
     -> SQLite (WAL + busy timeout)
```

核心数据包括：

- `events`：原始对话或外部事件。
- `memories`：从事件抽取的结构化长期记忆。
- `behavior_events`：用户的选择、拒绝和延后行为。
- `profile_traits`：由重复证据巩固出的稳定画像。
- `policy_signals`：关于何时读写记忆的学习信号。
- `context_packages`：面向具体任务编译的上下文包。
- `quality_traces`：策略、抽取、检索和巩固的审计轨迹。

## 2. 启动服务

```bash
uv sync
export PAM_OS_DB="$HOME/.pam-os/memory.sqlite3"
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

Windows PowerShell：

```powershell
$env:PAM_OS_DB = "$HOME\.pam-os\memory.sqlite3"
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

服务入口：

- 存活检查：`GET /health/live`
- 就绪检查：`GET /v1/health/ready`
- 版本信息：`GET /v1/meta`
- OpenAPI：`GET /openapi.json`
- Swagger UI：`GET /docs`

## 3. 服务端配置

复制示例：

```bash
cp config/pam-os.example.toml config/pam-os.toml
```

常用配置：

```toml
[storage]
db_path = "~/.pam-os/memory.sqlite3"

[server]
host = "127.0.0.1"
port = 8765
auth_enabled = true
auth_username = "user"
auth_password = "change-me"

[context]
default_limit = 12
max_chars = 4000
profile_limit = 8
```

环境变量会覆盖 TOML：

```text
PAM_OS_DB
PAM_OS_CONFIG
PAM_OS_HOST
PAM_OS_PORT
PAM_OS_AUTH_ENABLED
PAM_OS_AUTH_USERNAME
PAM_OS_AUTH_PASSWORD
```

## 4. Skill 配置

安装后的每个客户端 skill 都读取自己的 `config.toml`：

```toml
[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
timeout_seconds = 10
```

规则：

- `url` 必须存在。
- 用户名和密码都非空时发送 Basic Auth。
- 服务不在 localhost 时必须使用 HTTPS。
- API 不可达时直接提示启动或配置服务，不回退到本地进程。
- 写请求默认不自动重试，避免重复事件。

## 5. 推荐记忆循环

### 5.1 回答前：prepare

当任务依赖用户偏好、项目历史、历史决策、长期目标、回答风格或上下文连续性时调用：

```http
POST /v1/context/prepare
Content-Type: application/json

{
  "task": "按我的偏好继续设计 PAM-OS",
  "conversation_summary": null,
  "force": false,
  "limit": null,
  "max_chars": null
}
```

返回的 `package.content` 是最终可注入模型的文本。`usage_summary` 用于向用户显示简短的记忆使用状态。

### 5.2 回答后：observe turn

每个 substantial user-facing turn 完成后调用：

```http
POST /v1/turns/observe
Content-Type: application/json

{
  "user_message": "用户消息",
  "assistant_message": "助手最终回答",
  "conversation_summary": null,
  "source_ref": null,
  "auto_capture": true,
  "auto_learn_policy": true
}
```

substantial turn 包括分析、排障、实现、规划、决策、偏好、纠正、多步任务和项目上下文。短确认、纯状态更新和没有有效结果的失败轮次可以跳过。

### 5.3 显式写入：capture

用户明确要求“记住”或导入稳定内容时使用：

```http
POST /v1/memory/capture
Content-Type: application/json

{
  "content": "用户偏好本地优先、轻量、可控的设计。",
  "source": "assistant",
  "source_ref": null,
  "metadata": {},
  "force": true
}
```

普通轮次不要用 capture 替代 observe-turn。

## 6. API 参考

### 6.1 事件与检索

```http
POST /v1/events
{"content":"raw event","source":"manual","source_ref":null,"metadata":{},"extract":true}
```

```http
POST /v1/memories/search
{"query":"SQLite FTS5","limit":10,"types":["project"],"min_importance":0.0,"min_confidence":0.0}
```

搜索改为 POST body，避免把可能敏感的查询文本放入 URL 和访问日志。

### 6.2 策略判断

```http
POST /v1/memory/should-use
{"task":"继续之前的项目","conversation_summary":null}
```

### 6.3 行为与画像

```http
POST /v1/behavior/choice
{"context":"存储选型","chosen":["SQLite FTS5"],"rejected":["Qdrant"],"deferred":[],"reason":"保持轻量","source_ref":null}
```

```http
POST /v1/memory/consolidate
{"recent":100}
```

```http
GET /v1/profile?limit=20&q=技术路线
```

### 6.4 上下文

```http
POST /v1/context/compile
{"task":"继续 PAM-OS","limit":8,"min_importance":0.0,"min_confidence":0.5}
```

```http
POST /v1/reflect
{"recent":50}
```

### 6.5 诊断与维护

```http
GET /v1/storage/stats
GET /v1/memory/inspect?table=quality_traces&limit=20
```

清空是不可逆操作：

```http
POST /v1/memory/clear
{"confirm":true}
```

skill 只有在用户明确要求清理时才能调用该接口。

## 7. 请求校验与错误

请求模型会：

- 拒绝未知字段。
- 拒绝 `Content-Length` 超过 1 MB 的请求体。
- 拒绝空字符串和超长文本。
- 将分数约束在 `0.0..1.0`。
- 限制检索、画像和诊断返回条数。
- 限制巩固和反思窗口。

结构化错误示例：

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": []
  }
}
```

## 8. 安全边界

当前版本是单实例、单用户数据库模型。客户端不能再通过 `user_id` 或 `X-PAM-OS-User` 切换数据库。

原因是旧实现只有文件分片，没有把用户身份绑定到认证主体；任何持有同一 Basic Auth 的客户端都能声明任意用户。这属于数据分区，不是授权隔离。

如果未来需要真正多租户，应实现：

```text
credential/token -> authenticated subject -> fixed tenant -> tenant storage
```

在此之前建议一名用户一个 PAM-OS 实例。

## 9. SQLite

`MemoryStore` 当前使用：

- 每次操作独立短连接。
- `PRAGMA foreign_keys = ON`。
- 5 秒连接超时和 `busy_timeout`。
- 初始化时启用 WAL。
- `synchronous = NORMAL`。

事件与本次抽取/去重后的记忆已经在同一事务内提交，避免出现只有 event、没有 memory 的部分写入。质量 trace 仍单独写入；如果未来需要严格的全链路原子性，可以再把 trace 纳入同一工作单元。

## 10. Docker

```bash
docker build -t pam-os .
docker run -d --name pam-os \
  -p 8765:8765 \
  -v pam-os-data:/data \
  -e PAM_OS_AUTH_ENABLED=true \
  -e PAM_OS_AUTH_USERNAME=user \
  -e PAM_OS_AUTH_PASSWORD=change-me \
  pam-os
```

镜像直接运行 `uvicorn pam_os.api:create_app --factory`，健康检查访问 `/health/live`。

## 11. 安装 Agent 集成

```bash
./scripts/install-plugin.sh --codex --yes
./scripts/install-plugin.sh --claude --yes
./scripts/install-plugin.sh --opencode --yes
./scripts/install-plugin.sh --hermes --yes
```

本地 checkout：

```bash
./scripts/install-plugin-local.sh
```

安装器只写 REST 配置。Unix 下配置权限设为 `0600`，Windows 下移除继承 ACL 并仅授予当前用户访问。

## 12. 开发接口

核心运行时仍可在 Python 内部直接使用，以便 API 层测试和 Provider 开发：

```python
from pam_os.runtime import PersonalMemoryRuntime

runtime = PersonalMemoryRuntime()
prepared = runtime.prepare_context("继续 PAM-OS", force=True)
```

这不是客户端集成方式。外部 Agent 应使用 REST。

质量评估使用：

```python
from pam_os.quality import evaluate_quality_cases

report = evaluate_quality_cases()
```

## 13. 迁移说明

- Python 包不再注册 `memory` / `pam-memory` 命令。
- `src/pam_os/cli.py` 已删除。
- FastAPI 与 Uvicorn 从可选依赖变为基础依赖。
- 正式 API 使用 `/v1`。
- 旧无版本路由暂时保留，但不出现在 OpenAPI 中。
- skill 配置删除 `mode` 和 `[cli]`。
- 数据库无需迁移；仍使用原 SQLite schema。
