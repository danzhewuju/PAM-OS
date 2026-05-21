# PAM-OS 使用文档

PAM-OS 是一个本地优先的 Personal AI Memory OS MVP。它提供一套轻量的个人记忆运行时，把对话或外部事件保存为原始事件，抽取为结构化记忆，写入 SQLite，再按任务检索并编译成可直接放进模型提示词的上下文。

当前版本的主链路是：

```text
Raw Event -> Memory Extraction -> SQLite Memory Store -> Retrieval -> Context Compilation
```

它适合用于：

- 为 AI 助手保存用户偏好、长期目标、项目决策和回答风格。
- 在回答前自动准备与用户、项目、历史决策相关的记忆上下文。
- 在回答后捕获稳定信息，而跳过短暂闲聊。
- 通过行为选择逐步形成更稳定的用户画像。
- 通过 CLI 或 REST API 接入其他工具。

## 1. 环境要求

- Python 3.11 或更高版本。README 示例使用 Python 3.12。
- 推荐使用 `uv` 运行项目命令。
- 默认不依赖外部服务。核心功能只使用 Python 标准库和 SQLite。
- REST API 需要安装 `api` 可选依赖。
- 开发和测试需要安装 `dev` 可选依赖。

## 2. 快速开始

在项目根目录运行：

```powershell
uv run --python 3.12 memory init
```

默认数据库会创建在：

```text
~/.pam-os/memory.sqlite3
```

写入一条记忆：

```powershell
uv run --python 3.12 memory add "我今天在思考 Personal AI Memory OS，倾向先做本地 REST 服务，不想一开始引入重型组件。"
```

搜索记忆：

```powershell
uv run --python 3.12 memory search "Personal AI Memory OS 下一步实现"
```

为当前任务准备上下文：

```powershell
uv run --python 3.12 memory prepare "我现在想继续做 Personal AI Memory OS，下一步怎么做？"
```

`prepare` 默认输出 prompt-ready 文本。如果需要完整 JSON：

```powershell
uv run --python 3.12 memory prepare "我现在想继续做 Personal AI Memory OS，下一步怎么做？" --json
```

## 3. 项目结构

```text
PAM-OS/
  config/
    pam-os.example.toml       示例配置
  docs/
    design/                   设计文档
    usage.md                  本使用文档
  src/pam_os/
    cli.py                    CLI 入口
    runtime.py                核心运行时门面
    store.py                  SQLite 存储、检索、画像表操作
    extractor.py              规则抽取器
    orchestrator.py           记忆读写决策、预算、重排
    context.py                上下文编译器
    consolidator.py           画像证据与画像特征巩固
    api.py                    REST API
    config.py                 配置加载
    models.py                 数据模型
  tests/
    test_runtime.py           端到端运行时测试
  pyproject.toml              包配置、命令入口、可选依赖
```

## 4. 配置

复制示例配置：

```powershell
Copy-Item config\pam-os.example.toml config\pam-os.toml
```

配置加载优先级为：

```text
CLI arguments > environment variables > config/pam-os.toml > built-in defaults
```

常用环境变量：

```powershell
$env:PAM_OS_DB = "C:\path\to\memory.sqlite3"
$env:PAM_OS_CONFIG = "C:\path\to\pam-os.toml"
```

也可以通过 CLI 指定：

```powershell
uv run --python 3.12 memory --config C:\path\to\pam-os.toml prepare "我继续做 PAM-OS"
uv run --python 3.12 memory --db C:\path\to\memory.sqlite3 search "PAM-OS"
```

主要配置段：

| 配置段 | 作用 |
| --- | --- |
| `[storage]` | SQLite 数据库路径。 |
| `[server]` | REST API 的 host 和 port。 |
| `[context]` | 默认记忆条数、上下文字符预算、画像注入条数。 |
| `[consolidation]` | 每次巩固扫描多少记忆/行为事件，以及稳定性和置信度增长上限。 |
| `[orchestrator]` | 是否读取记忆、是否捕获记忆、候选记忆扩展倍数。 |
| `[retrieval]` | 查询词提取上限。 |
| `[profile]` | `memory profile` 默认返回画像条数。 |

示例配置见 `config/pam-os.example.toml`。

## 5. 核心概念

### 5.1 Raw Event

原始事件是进入系统的原始文本。它可以来自手动输入、对话、外部工具或其他集成源。原始事件会永久保存在 `events` 表中。

### 5.2 Memory

记忆是从原始事件中抽取出的结构化信息。当前支持类型：

| 类型 | 含义 |
| --- | --- |
| `preference` | 用户偏好、倾向、喜欢或不喜欢。 |
| `goal` | 用户目标、计划、下一步。 |
| `project` | 项目上下文、技术决策、MVP 信息。 |
| `style` | 回答风格、语气、沟通偏好。 |
| `episodic` | 最近发生的具体事件。 |
| `semantic` | 一般事实或知识。 |

每条记忆包含：

- `content`：记忆内容。
- `importance`：重要性，0 到 1。
- `confidence`：置信度，0 到 1。
- `tags`：检索标签。
- `valid_from` / `valid_to`：有效期，当前 MVP 中通常为空。

### 5.3 Profile Evidence 和 Profile Trait

PAM-OS 不会把一次事件直接当作永久人格判断。画像层分两步：

```text
Extracted Memories / Behavior Events -> Profile Evidence -> Profile Traits
```

`ProfileEvidence` 是证据，说明系统为什么相信某个特征。`ProfileTrait` 是更稳定的用户画像，例如：

```text
用户长期偏好 self-host、开源、本地可控的系统。
用户做技术决策时倾向先选择轻量、本地、可控、可运行的方案验证闭环，再逐步引入复杂基础设施。
```

### 5.4 Context Package

上下文包是给模型使用的最终文本。它会按类型分区：

```text
# User Memory Context

Current task: ...

## User Profile
- ...

## Long-term Preferences
- ...

## Active Projects
- ...
```

`prepare` 和 `compile` 都会保存生成过的上下文包。

## 6. 推荐工作流

### 6.1 模型回答前：使用 `prepare`

当用户问题依赖个人偏好、长期目标、已有项目、历史决策或“继续之前的事”时，使用：

```powershell
uv run --python 3.12 memory prepare "我继续做 PAM-OS，下一步怎么做？"
```

`prepare` 会做这些事：

1. 判断当前任务是否需要读取记忆。
2. 如果不需要，返回跳过原因。
3. 如果需要，检索候选记忆。
4. 对结果重排。
5. 按类型和字符预算筛选。
6. 优先注入稳定用户画像。
7. 输出可直接用于提示词的上下文包。

如果确定一定要使用记忆，可以加 `--force`：

```powershell
uv run --python 3.12 memory prepare "给我一个符合我偏好的实现方案" --force
```

如果想获得决策、上下文包和检索结果的完整结构：

```powershell
uv run --python 3.12 memory prepare "我继续做 PAM-OS，下一步怎么做？" --json
```

### 6.2 模型回答后：使用 `capture`

当用户透露稳定信息时，用 `capture` 捕获：

```powershell
uv run --python 3.12 memory capture "我决定 PAM-OS v0.1 先用 SQLite FTS5，不引入 Qdrant。"
```

适合捕获的内容：

- 长期偏好。
- 长期目标。
- 项目决策。
- 回答风格要求。
- 用户纠正了系统对自己的理解。

不适合捕获的内容：

- “哈哈好的”这类临时闲聊。
- 一次性的普通事实问题。
- 没有长期价值的短期状态。

如果必须写入，可以加 `--force`：

```powershell
uv run --python 3.12 memory capture "我决定 PAM-OS v0.1 先用 SQLite FTS5，不引入 Qdrant。" --force
```

### 6.3 记录行为选择

当用户在多个方案中选择、拒绝或暂缓时，用行为事件记录：

```powershell
uv run --python 3.12 memory behavior-choice `
  --context "PAM-OS 技术路线" `
  --chosen "SQLite FTS5" `
  --rejected "Qdrant" `
  --rejected "Neo4j" `
  --reason "MVP 阶段先保持本地、轻量、可控"
```

行为选择不是普通记忆，它会先进入 `behavior_events`，随后通过 `consolidate` 转成画像证据和画像特征。

### 6.4 定期巩固画像

```powershell
uv run --python 3.12 memory consolidate --recent 100
```

查看画像：

```powershell
uv run --python 3.12 memory profile
```

按查询过滤画像：

```powershell
uv run --python 3.12 memory profile --query "技术路线"
```

### 6.5 加载到大模型客户端中使用

PAM-OS 接入大模型客户端时，建议把职责拆成两层：

```text
REST API = 给模型真实工具能力：prepare_context、capture_memory、search_memory 等
Skill    = 给模型操作策略：什么时候读记忆、什么时候写记忆、什么不要保存
```

也就是说，Skill 负责“会判断”，运行模式负责“怎么调用”。默认推荐 CLI + Skill：不需要启动长驻 REST 服务，模型按 skill 说明运行本地 `memory` 命令。只有当你明确选择 REST 模式时，才需要启动 REST server 并配置 REST URL。

本仓库已经内置两个项目级 Skill：

| 客户端 | Skill 路径 | 作用 |
| --- | --- | --- |
| Codex | `.agents/skills/pam-os-memory/SKILL.md` | Codex 会在仓库内自动扫描 repo skill。 |
| Claude Code | `.claude/skills/pam-os-memory/SKILL.md` | Claude Code 会在仓库内自动扫描 project skill。 |

Skill 的触发场景包括：

- 用户说“继续之前的项目”“按我的偏好”“记得我上次说的”等。
- 用户问题涉及长期目标、项目历史、历史决策、回答风格。
- 用户明确要求“记住这个”。
- 用户在多个选项中选择、拒绝或暂缓某些方案。

#### Codex CLI / IDE

Codex 支持从 repo、user、admin 和 system 位置读取 Skills。当前仓库的 Codex Skill 已放在：

```text
.agents/skills/pam-os-memory/SKILL.md
```

在项目根目录启动 Codex 后，可以让 Codex 检查：

```text
List available skills
```

或显式提到：

```text
Use $pam-os-memory. 继续做 PAM-OS，按我的历史偏好给下一步计划。
```

Codex 直接使用 skill 即可。若要走 REST，把 skill 配置里的 `mode` 改成 `rest`，并确保 REST 服务已启动。

#### Claude Code

Claude Code 支持项目级 Skills。本仓库已经提供：

```text
.claude/skills/pam-os-memory/SKILL.md
```

进入项目根目录启动 Claude Code 后，可以问：

```text
List all available Skills
```

如果 Claude Code 已经运行，修改或新增 Skill 后通常需要重启会话才能重新加载。

如果你更偏向 REST 方式，可以把 skill 配置里的 `mode` 设成 `rest`，然后确保 PAM-OS REST 服务已启动。

#### CC Switch

如果你使用 CC Switch，可以把 PAM-OS 当作一组“Skills + REST API”配置导入。推荐配置方式：

1. 在 CC Switch 的目标应用中选择 Codex 或 Claude Code。
2. 在 Skills 管理中添加本仓库的 skill 目录：
   - Codex: `.agents/skills/pam-os-memory`
   - Claude Code: `.claude/skills/pam-os-memory`
3. 在 REST 配置中填写 PAM-OS 服务地址和认证信息。
4. 同步或启用到对应客户端。
5. 重启 Codex / Claude Code，并用“List available skills”检查加载结果。

不同版本的 CC Switch UI 可能略有差异，但核心信息就是这三件事：Skill 目录、REST 地址、环境变量。

#### 建议给模型的系统提示片段

如果客户端不支持 Skills，可以把下面这段放进系统提示或项目规则中：

```text
Use PAM-OS as local long-term memory.
Before answering, call prepare_context when the task depends on user preferences,
ongoing projects, prior decisions, long-term goals, answer style, or previous
conversation history. Do not call it for generic one-off factual questions.

After answering, call capture_memory only for stable user preferences, goals,
project decisions, style guidance, or corrections. Do not capture transient chat
or secrets. When the user chooses/rejects/defers options, call
record_behavior_choice. Periodically call consolidate_memory.
```

#### 验证是否接入成功

先写入一条测试记忆：

```powershell
uv run --python 3.12 memory capture "我偏好本地优先、轻量、可控的技术方案。" --force
```

然后在 Codex 或 Claude Code 中问：

```text
按我的偏好，PAM-OS 下一步应该怎么做？
```

成功接入时，模型应该先调用 `prepare_context`，读到“本地优先、轻量、可控”等偏好，再基于这些上下文回答。

## 7. CLI 命令详解

所有命令都通过 `memory` 入口运行：

```powershell
uv run --python 3.12 memory <command>
```

全局参数：

| 参数 | 说明 |
| --- | --- |
| `--config` | 指定 TOML 配置文件。默认读取 `PAM_OS_CONFIG` 或 `config/pam-os.toml`。 |
| `--db` | 指定 SQLite 数据库路径。优先级高于配置文件。 |

注意：全局参数要写在子命令前：

```powershell
uv run --python 3.12 memory --db .pam-os\demo.sqlite3 init
```

### 7.1 `init`

初始化数据库：

```powershell
uv run --python 3.12 memory init
```

`MemoryStore` 初始化时也会自动建表，所以显式 `init` 主要用于首次检查路径和手动初始化。

### 7.2 `add`

低层写入命令：保存原始事件，并默认抽取记忆。

```powershell
uv run --python 3.12 memory add "我偏好 self-host 和本地可控系统。"
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--source` | 来源，默认 `manual`。 |
| `--source-ref` | 外部引用，例如会话 ID、文件路径、消息 ID。 |
| `--metadata-json` | 附加 JSON 元数据。 |
| `--no-extract` | 只保存原始事件，不抽取记忆。 |

示例：

```powershell
uv run --python 3.12 memory add "用户偏好直接、工程化、可执行的回答。" `
  --source "import" `
  --source-ref "notes/answer-style.md" `
  --metadata-json "{\"explicit_memory\": true}"
```

### 7.3 `capture`

推荐的写入命令：先判断内容是否值得长期保存，再决定是否调用 `remember`。

```powershell
uv run --python 3.12 memory capture "我偏好 self-host、开源、可控系统。"
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--source` | 来源，默认 `conversation`。 |
| `--source-ref` | 外部引用。 |
| `--metadata-json` | 附加 JSON 元数据。 |
| `--force` | 跳过捕获判断，强制保存。 |

`capture` 的返回 JSON 包含：

- `should_capture`：是否写入。
- `reason`：写入或跳过原因。
- `event`：写入的原始事件。
- `memories`：抽取出的记忆。

### 7.4 `search`

搜索记忆：

```powershell
uv run --python 3.12 memory search "self-host 本地可控" --limit 5
```

按类型过滤：

```powershell
uv run --python 3.12 memory search "回答风格" --type style
uv run --python 3.12 memory search "PAM-OS" --type project --type goal
```

如果 SQLite 支持 FTS5，会优先使用 FTS5；否则回退到 `LIKE` 查询。

### 7.5 `should-use`

只判断一个任务是否需要读记忆，不实际检索上下文：

```powershell
uv run --python 3.12 memory should-use "Python list 怎么排序？"
uv run --python 3.12 memory should-use "按我的偏好设计 PAM-OS 下一步"
```

它会返回：

- `should_use`：是否建议读取记忆。
- `reason`：判断原因。
- `confidence`：置信度。
- `signals`：命中的信号。

### 7.6 `prepare`

推荐的读路径。比 `search` 和 `compile` 更适合模型集成。

```powershell
uv run --python 3.12 memory prepare "按我的偏好设计 PAM-OS 下一步"
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--conversation-summary` | 当前对话摘要，会加入检索 query。 |
| `--force` | 即使判断不需要记忆，也强制准备上下文。 |
| `--limit` | 最多选入多少普通记忆。 |
| `--max-chars` | 最终上下文包最大字符数。 |
| `--json` | 输出完整 JSON，而不是只输出上下文文本。 |

示例：

```powershell
uv run --python 3.12 memory prepare `
  "我继续做 PAM-OS，下一步怎么做？" `
  --conversation-summary "前面讨论过本地优先、SQLite、REST API" `
  --limit 8 `
  --max-chars 3000 `
  --json
```

### 7.7 `compile`

低层上下文编译命令。它会直接按任务搜索记忆并生成上下文包，不做 `should-use` 门控、不注入画像层。

```powershell
uv run --python 3.12 memory compile "我继续做 Personal AI Memory OS"
```

一般模型集成优先使用 `prepare`。

### 7.8 `behavior-choice`

记录用户选择、拒绝和暂缓的方案：

```powershell
uv run --python 3.12 memory behavior-choice `
  --context "回答风格选择" `
  --chosen "直接给结论和操作步骤" `
  --rejected "营销式长篇解释"
```

`--chosen`、`--rejected`、`--deferred` 都可以重复传多次。

### 7.9 `consolidate`

把近期记忆和行为事件提升为画像证据和画像特征：

```powershell
uv run --python 3.12 memory consolidate --recent 100
```

返回结果包含：

- `evidence_created`：新建的画像证据。
- `traits_updated`：更新的画像特征。
- `memories_scanned`：扫描的未巩固记忆数。
- `behavior_events_scanned`：扫描的未巩固行为事件数。

### 7.10 `profile`

查看稳定画像：

```powershell
uv run --python 3.12 memory profile
uv run --python 3.12 memory profile --limit 5
uv run --python 3.12 memory profile --query "self-host"
```

### 7.11 `reflect`

从最近记忆中编译一个反思上下文：

```powershell
uv run --python 3.12 memory reflect --recent 50
```

### 7.12 `serve`

启动 REST API：

```powershell
uv run --python 3.12 --extra api memory serve --host 127.0.0.1 --port 8765
```

### 7.13 `stats`

查看存储概览：

```powershell
uv run --python 3.12 memory stats
```

返回内容包括数据库路径、文件大小、FTS 状态、最近写入时间，以及各表的分表统计。

### 7.14 `inspect`

查看各表记忆明细和统计：

```powershell
uv run --python 3.12 memory inspect
uv run --python 3.12 memory inspect --table memories --limit 10
uv run --python 3.12 memory inspect --table memories --query self-host
```

输出 JSON：

```powershell
uv run --python 3.12 memory inspect --json
```

`--table` 支持 `all`、`events`、`memories`、`profile_evidence`、`profile_traits`、`behavior_events`、`context_packages` 和 `memory_links`。REST 中的对应接口是 `GET /memory/inspect`。

### 7.15 `clear`

清空所有记忆相关数据，包括原始事件、结构化记忆、画像、行为事件和上下文包：

```powershell
uv run --python 3.12 memory clear --confirm
```

`clear` 是不可逆操作，必须显式传入 `--confirm`，否则命令会拒绝执行。

## 8. 显式 JSON 记忆写入

规则抽取器支持直接输入 JSON 或 fenced JSON。这样可以精确控制类型、重要性、置信度和标签。

```powershell
uv run --python 3.12 memory add '
[
  {
    "type": "preference",
    "content": "用户偏好 self-host 和本地可控系统。",
    "importance": 0.9,
    "confidence": 0.85,
    "tags": ["self-host", "control"]
  }
]'
```

支持字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `content` | 是 | 记忆内容。 |
| `type` | 否 | 记忆类型，非法值会回退到 `semantic`。 |
| `importance` | 否 | 0 到 1，默认 0.6。 |
| `confidence` | 否 | 0 到 1，默认 0.7。 |
| `tags` | 否 | 字符串数组。 |

支持的 `type` 值：

```text
semantic, episodic, preference, goal, project, style
```

## 9. REST API

启动服务：

```powershell
uv run --python 3.12 --extra api memory serve --host 127.0.0.1 --port 8765
```

健康检查：

```powershell
curl http://127.0.0.1:8765/health
```

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查、数据库路径、FTS 状态。 |
| `POST` | `/events` | 低层写入事件并抽取记忆。 |
| `GET` | `/memories/search?q=...` | 搜索记忆。 |
| `GET` | `/memory/inspect?table=all&limit=20&q=...` | 查看各表记忆明细和统计。 |
| `GET` | `/memory/should-use?task=...` | 判断是否需要读记忆。 |
| `POST` | `/context/prepare` | 推荐的回答前上下文准备。 |
| `POST` | `/memory/capture` | 推荐的回答后记忆捕获。 |
| `POST` | `/behavior/choice` | 记录用户行为选择。 |
| `POST` | `/memory/consolidate` | 巩固画像。 |
| `GET` | `/profile` | 查看画像。 |
| `POST` | `/context/compile` | 低层上下文编译。 |
| `POST` | `/reflect` | 最近记忆反思上下文。 |
| `GET` | `/storage/stats` | 查看存储概览。 |
| `POST` | `/memory/clear` | 清空所有记忆、画像、上下文包和原始事件。 |

写入事件：

```powershell
curl -X POST http://127.0.0.1:8765/events `
  -H "Content-Type: application/json" `
  -d "{\"content\":\"我偏好 self-host 和本地可控系统。\",\"source\":\"manual\",\"extract\":true}"
```

准备上下文：

```powershell
curl -X POST http://127.0.0.1:8765/context/prepare `
  -H "Content-Type: application/json" `
  -d "{\"task\":\"我继续做 PAM-OS，下一步怎么做？\",\"force\":false,\"limit\":8,\"max_chars\":3000}"
```

捕获记忆：

```powershell
curl -X POST http://127.0.0.1:8765/memory/capture `
  -H "Content-Type: application/json" `
  -d "{\"content\":\"我决定 PAM-OS v0.1 先用 SQLite FTS5，不引入 Qdrant。\"}"
```

记录行为选择：

```powershell
curl -X POST http://127.0.0.1:8765/behavior/choice `
  -H "Content-Type: application/json" `
  -d "{\"context\":\"PAM-OS 技术路线\",\"chosen\":[\"SQLite FTS5\"],\"rejected\":[\"Qdrant\",\"Neo4j\"],\"reason\":\"MVP 阶段先保持本地、轻量、可控\"}"
```

查看画像：

```powershell
curl "http://127.0.0.1:8765/profile?limit=10&q=self-host"
```

查看记忆明细：

```powershell
curl "http://127.0.0.1:8765/memory/inspect?table=all&limit=20"
curl "http://127.0.0.1:8765/memory/inspect?table=memories&limit=10&q=self-host"
```

`table` 支持 `all`、`events`、`memories`、`profile_evidence`、`profile_traits`、`behavior_events`、`context_packages` 和 `memory_links`。

清空所有记忆数据：

```powershell
curl -X POST http://127.0.0.1:8765/memory/clear `
  -H "Content-Type: application/json" `
  -d "{\"confirm\":true}"
```

`/memory/clear` 是不可逆操作，必须显式传入 `confirm: true`，否则会返回 `400`。

REST 服务启动后，FastAPI 也会提供：

```text
http://127.0.0.1:8765/docs
```

## 10. Python API

可以直接在 Python 中使用核心运行时：

```python
from pam_os import PersonalMemoryRuntime

runtime = PersonalMemoryRuntime(db_path="~/.pam-os/memory.sqlite3")

runtime.capture_memory(
    "我决定 PAM-OS v0.1 先用 SQLite FTS5，不引入 Qdrant。",
    force=True,
)

prepared = runtime.prepare_context("我继续做 PAM-OS，下一步怎么做？")
if prepared.package:
    print(prepared.package.content)
```

常用方法：

| 方法 | 说明 |
| --- | --- |
| `init()` | 初始化数据库。 |
| `remember(content, ...)` | 低层写入原始事件，并可抽取记忆。 |
| `search_memory(query, ...)` | 搜索记忆。 |
| `should_use_memory(task, ...)` | 判断回答前是否需要读记忆。 |
| `prepare_context(task, ...)` | 推荐读路径，返回 `PreparedContext`。 |
| `should_capture_memory(content, ...)` | 判断回答后是否应捕获。 |
| `capture_memory(content, ...)` | 推荐写路径，返回 `CaptureResult`。 |
| `record_behavior_choice(...)` | 记录用户行为选择。 |
| `consolidate_memory(...)` | 巩固画像。 |
| `get_user_profile(...)` | 读取画像。 |
| `compile_context(task, ...)` | 低层上下文编译。 |
| `reflect(recent=50)` | 从近期记忆编译反思上下文。 |
| `clear_memory()` | 清空所有记忆相关数据并返回删除统计。 |
| `inspect_memory(table="all", limit=20, query=None)` | 查看各表记忆明细和统计。 |

使用配置对象：

```python
from pam_os.config import load_config
from pam_os.runtime import PersonalMemoryRuntime

config = load_config("config/pam-os.toml")
runtime = PersonalMemoryRuntime(config=config)
```

## 11. 数据存储

PAM-OS 使用 SQLite。初始化时会创建这些表：

| 表 | 说明 |
| --- | --- |
| `events` | 原始事件。 |
| `memories` | 抽取后的结构化记忆。 |
| `memories_fts` | FTS5 虚拟表；如果当前 SQLite 不支持 FTS5，会自动回退。 |
| `memory_links` | 记忆之间的关系表，当前 MVP 预留。 |
| `context_packages` | 已生成的上下文包。 |
| `profile_evidence` | 用户画像证据。 |
| `profile_traits` | 稳定用户画像。 |
| `behavior_events` | 用户行为选择事件。 |

默认数据库位于 `~/.pam-os/memory.sqlite3`，因此不同终端和不同项目会共用同一份本机记忆库。

## 12. 检索和抽取规则

### 13.1 抽取

当前默认抽取器是 `RuleBasedExtractor`：

- 如果输入是 JSON 或 fenced JSON，则按显式 JSON 抽取。
- 否则按关键字推断记忆类型。
- 自动生成标签、重要性和置信度。

部分推断规则：

| 内容特征 | 推断类型 |
| --- | --- |
| 包含“偏好、喜欢、不喜欢、倾向”等 | `preference` |
| 包含“回答风格、风格、语气”等 | `style` |
| 包含“目标、计划、下一步”等 | `goal` |
| 包含“项目、MVP、正在做、OS”等 | `project` |
| 包含“今天、昨天、最近、刚刚”等 | `episodic` |
| 其他 | `semantic` |

### 13.2 检索

检索优先使用 SQLite FTS5：

```text
memories_fts MATCH ...
```

如果 FTS5 不可用或查询失败，回退到：

```text
content LIKE ... OR tags_json LIKE ...
```

查询词会从文本中提取：

- 空格分词。
- ASCII 单词。
- 一些常见中文关键词，例如“偏好、项目、目标、风格、实现、本地、可控、长期、思源”等。

### 13.3 `prepare` 重排和预算

`prepare` 会对候选记忆重新打分。因素包括：

- 检索相关性。
- 记忆重要性。
- 记忆置信度。
- 最近更新时间。
- 稳定性类型加权。

然后按类型限制和字符预算筛选，避免某一种记忆挤占上下文。

## 13. 常见集成模式

### 14.1 作为本地 AI 助手记忆层

推荐循环：

```text
用户提问
  -> 调用 prepare_context
  -> 把 package.content 加入模型上下文
  -> 模型回答
  -> 如果用户或回答中出现稳定信息，调用 capture_memory
  -> 如果用户做出选择，调用 record_behavior_choice
  -> 周期性调用 consolidate_memory
```

### 14.2 作为手动知识库

低层命令即可：

```powershell
uv run --python 3.12 memory add "..."
uv run --python 3.12 memory search "..."
uv run --python 3.12 memory compile "..."
```

### 14.3 作为长期用户画像系统

重点使用：

```powershell
uv run --python 3.12 memory capture "我偏好 self-host、开源、可控系统。"
uv run --python 3.12 memory behavior-choice --context "技术路线" --chosen "SQLite FTS5" --rejected "Qdrant"
uv run --python 3.12 memory consolidate
uv run --python 3.12 memory profile
uv run --python 3.12 memory prepare "按我的偏好设计下一步"
```

## 14. 开发和测试

运行测试：

```powershell
uv run --python 3.12 --extra dev pytest
```

只运行运行时测试：

```powershell
uv run --python 3.12 --extra dev pytest tests\test_runtime.py
```

检查 CLI：

```powershell
uv run --python 3.12 memory --help
uv run --python 3.12 memory prepare --help
```

## 15. 常见问题

### 16.1 `prepare` 没有返回上下文

`prepare` 会先判断任务是否需要记忆。普通问题可能只返回决策结果。例如：

```powershell
uv run --python 3.12 memory prepare "Python list 怎么排序？" --json
```

如果确定要强制使用记忆：

```powershell
uv run --python 3.12 memory prepare "Python list 怎么排序？" --force
```

### 16.2 `capture` 没有写入

`capture` 会跳过短暂内容。例如“哈哈好的”通常不会保存。要强制保存：

```powershell
uv run --python 3.12 memory capture "哈哈好的" --force
```

### 16.3 搜索结果为空

可能原因：

- 数据库路径不是你以为的那个。检查 `PAM_OS_DB`、`--db` 和配置文件。
- 之前用的是 `--no-extract`，只保存了事件，没有生成记忆。
- query 词和记忆内容差异太大。
- 当前数据库还没有相关记忆。

可以先查看当前数据库路径：

```powershell
uv run --python 3.12 memory --help
```

或通过 REST：

```powershell
curl http://127.0.0.1:8765/health
```

### 15.4 REST 报依赖缺失

REST 需要：

```powershell
uv run --python 3.12 --extra api memory serve
```

### 15.5 PowerShell JSON 转义麻烦

复杂 JSON 可以优先写入文件，再用命令读取文件内容；或者在 Python API / REST 客户端里传结构化对象。简单 JSON 在 PowerShell 里通常需要转义双引号：

```powershell
uv run --python 3.12 memory add "用户偏好本地可控系统。" --metadata-json "{\"explicit_memory\": true}"
```

### 15.6 配置文件没有生效

检查优先级：

```text
CLI arguments > environment variables > config/pam-os.toml > built-in defaults
```

如果设置了 `PAM_OS_DB`，它会覆盖 `[storage].db_path`。

## 16. 当前 MVP 边界

- 抽取器是规则版，不调用 LLM。
- 画像巩固也是规则版，主要覆盖偏好、回答风格、技术决策风格等有限模式。
- 检索是 SQLite FTS5 或 LIKE，不包含向量数据库。
- `memory_links` 表已预留，但当前没有复杂图谱逻辑。
- 上下文预算按字符裁剪，不是精确 token 预算。
- 原始事件会保存；如需手动遗忘，可通过 REST `/memory/clear` 一次性清空全部记忆数据。

这些边界也是当前版本的设计取舍：先保持本地、轻量、可运行，后续可以在相同接口后面替换为 LLM 抽取器、向量检索或更复杂的画像巩固逻辑。
