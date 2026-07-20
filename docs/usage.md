# PAM-OS 使用文档

PAM-OS v0.5 使用多用户 `/v2` REST API。核心 `PersonalMemoryRuntime` 仍保持协议无关，API 层通过认证主体把请求路由到用户专属 SQLite。

## 1. 架构

```text
Agent / Skill
  -> REST API
     -> Bearer API Key / scopes / 错误映射
     -> authenticated user -> UserRuntimeFactory
     -> 用户专属 PersonalMemoryRuntime
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
export PAM_OS_BOOTSTRAP_TOKEN='replace-with-a-long-random-secret'
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

Windows PowerShell：

```powershell
$env:PAM_OS_BOOTSTRAP_TOKEN = "replace-with-a-long-random-secret"
uv run python -m uvicorn pam_os.api:create_app --factory --host 127.0.0.1 --port 8765
```

服务入口：

- 存活检查：`GET /health/live`
- 就绪检查：`GET /v2/health/ready`
- 版本信息：`GET /v2/meta`
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
data_dir = "~/.pam-os"
control_db_path = ""
runtime_cache_size = 128

[server]
host = "127.0.0.1"
port = 8765
bootstrap_token = "replace-with-a-long-random-secret"

[context]
default_limit = 12
max_chars = 4000
profile_limit = 8
```

环境变量会覆盖 TOML：

```text
PAM_OS_DATA_DIR
PAM_OS_CONTROL_DB
PAM_OS_RUNTIME_CACHE_SIZE
PAM_OS_CONFIG
PAM_OS_HOST
PAM_OS_PORT
PAM_OS_BOOTSTRAP_TOKEN
```

## 4. Skill 配置

安装后的每个客户端 skill 都带有自己的 `config.toml`，但大模型不得直接读取它。所有 REST 操作都通过同目录的安全客户端完成（PowerShell 使用 `scripts/pam_client.ps1`，Bash 使用 `scripts/pam_client.sh`），由客户端在进程内加载凭据：

```toml
[versions]
skill = "0.5.1"
api = "v2"
server = "0.5.1"
server_api = "v2"
server_checked_at = "2026-07-18T00:00:00Z"
status = "match"

[rest]
url = "http://127.0.0.1:8765"
token = ""
timeout_seconds = 10
```

规则：

- `url` 必须存在。
- 大模型不得打印配置、拼接认证头或直接调用 `curl` / `Invoke-RestMethod`。
- 安全客户端在进程内读取 Token 并发送认证头；命令参数和输出中不包含凭据。
- Token 固定绑定用户；请求不得发送 `user_id` 或 `X-PAM-OS-User`。
- 服务不在 localhost 时必须使用 HTTPS。
- API 不可达时直接提示启动或配置服务，不回退到本地进程。
- 写请求默认不自动重试，避免重复事件。

安装时不要使用内联 Token 参数。使用安全交互输入、已有配置、由宿主安全注入的 `PAM_OS_REST_TOKEN`，或 `--rest-token-file`。

## 5. 推荐记忆循环

### 5.1 回答前：prepare

当任务依赖用户偏好、项目历史、历史决策、长期目标、回答风格或上下文连续性时调用：

```http
POST /v2/context/prepare
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
POST /v2/turns/observe
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
POST /v2/memory/capture
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
POST /v2/events
{"content":"raw event","source":"manual","source_ref":null,"metadata":{},"extract":true}
```

```http
POST /v2/memories/search
{"query":"SQLite FTS5","limit":10,"types":["project"],"min_importance":0.0,"min_confidence":0.0}
```

搜索改为 POST body，避免把可能敏感的查询文本放入 URL 和访问日志。

### 6.2 策略判断

```http
POST /v2/memory/should-use
{"task":"继续之前的项目","conversation_summary":null}
```

### 6.3 行为与画像

```http
POST /v2/behavior/choice
{"context":"存储选型","chosen":["SQLite FTS5"],"rejected":["Qdrant"],"deferred":[],"reason":"保持轻量","source_ref":null}
```

```http
POST /v2/memory/consolidate
{"recent":100}
```

```http
GET /v2/profile?limit=20&q=技术路线
```

### 6.4 上下文

```http
POST /v2/context/compile
{"task":"继续 PAM-OS","limit":8,"min_importance":0.0,"min_confidence":0.5}
```

```http
POST /v2/reflect
{"recent":50}
```

### 6.5 诊断与维护

```http
GET /v2/storage/stats
GET /v2/memory/inspect?table=quality_traces&limit=20
```

清空是不可逆操作：

```http
POST /v2/memory/clear
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

当前版本实现了真正的认证与存储绑定：

```text
credential/token -> authenticated subject -> fixed tenant -> tenant storage
```

Bearer API Key 只保存哈希，并固定绑定 Principal 与用户。普通业务接口不接受客户端声明用户。每个用户使用 `data_dir/users/<immutable-user-id>/memory.sqlite3`，数据库内的 `store_metadata.owner_user_id` 会在打开时校验。用户创建、密钥创建/吊销以及清空记忆会写入身份控制库的审计日志。

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
  -e PAM_OS_BOOTSTRAP_TOKEN='replace-with-a-long-random-secret' \
  pam-os
```

镜像直接运行 `uvicorn pam_os.api:create_app --factory`，健康检查访问 `/health/live`。

## 11. 安装 Agent 集成

```bash
./scripts/install.sh --codex --yes
./scripts/install.sh --claude --yes
./scripts/install.sh --opencode --yes
./scripts/install.sh --hermes --yes
```

Windows 使用 `scripts/install.ps1`，参数相同。本地 checkout：

```bash
./scripts/install.sh --repo-dir "$PWD" --yes
```

安装器同时处理首次安装和更新；未指定目标时会自动识别已有集成。它会读取已有 skill 配置，把 URL、Bearer Token 和超时作为默认值，刷新托管 checkout，并把 skill/API 版本、服务端版本、探测时间和匹配状态写入配置。交互模式不会明文回显旧 Token。命令行参数和 `PAM_OS_REST_*` 环境变量优先于已有配置。Unix 下配置权限设为 `0600`，Windows 下移除继承 ACL 并仅授予当前用户访问。

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
- 正式 API 使用 `/v2`。
- 旧无版本路由暂时保留，但不出现在 OpenAPI 中。
- skill 配置删除 `mode` 和 `[cli]`。
- 数据库无需迁移；仍使用原 SQLite schema。
