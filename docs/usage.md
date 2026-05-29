# PAM-OS 使用文档

PAM-OS 是一个本地优先的 Personal AI Memory OS MVP。它提供一套轻量的个人记忆运行时，把对话或外部事件保存为原始事件，抽取为结构化记忆，写入 SQLite，再按任务检索并编译成可直接放进模型提示词的上下文。当前同一套运行时同时服务 Plugin/MCP、CLI 和 REST。

当前版本的主链路是：

```text
Task/Event
  -> Adaptive Memory Policy
       |-- Learned Policy Signals
       `-- Rule Policy Fallback
  -> Provider Pipeline
       |-- Extraction / Retrieval / Reranking
       `-- Profile Consolidation
  -> SQLite Store
       |-- Events / Memories / Behavior Evidence
       |-- Profile Traits
       `-- Policy Signals
  -> Context Package
```

它适合用于：

- 为 AI 助手保存用户偏好、长期目标、项目决策和回答风格。
- 在回答前自动准备与用户、项目、历史决策相关的记忆上下文。
- 在回答后捕获稳定信息，而跳过短暂闲聊。
- 通过行为选择逐步形成更稳定的用户画像。
- 通过 Plugin/MCP、CLI 或 REST API 接入其他工具。

## 1. 环境要求

- Python 3.11 或更高版本。README 示例使用 Python 3.12。
- 推荐使用 `uv` 运行项目命令。
- 默认不依赖外部服务。核心功能只使用 Python 标准库和 SQLite。
- REST API 需要安装 `api` 可选依赖。
- 开发和测试需要安装 `dev` 可选依赖。

## 2. 快速开始：插件安装

推荐通过插件接入 PAM-OS，这是最主要的使用方式。插件会托管运行仓库、注册 MCP server 和 skill，让 AI 客户端自动获得记忆读写能力。

### 2.1 一键安装

```bash
./scripts/install-plugin.sh --codex --yes
```

这个命令会写入：

- `~/.local/share/pam-os/repo`：托管运行仓库。
- `~/plugins/pam-os-memory`：个人 plugin 源目录。
- `~/.agents/plugins/marketplace.json`：个人 marketplace 入口。
- `~/.codex/skills/pam-os-memory`：全局 skill fallback。
- `~/.codex/config.toml`：`pam_os_memory` MCP server 注册。

### 2.2 支持的其他客户端

```bash
./scripts/install-plugin.sh --claude --yes
./scripts/install-plugin.sh --opencode --yes
./scripts/install-plugin.sh --hermes --yes
```

默认写入：

- Claude Code：`~/.claude/skills/pam-os-memory`
- OpenCode：`~/.config/opencode/AGENTS.md`，并复用 Claude-compatible skill
- Hermes：`~/.hermes/config.yaml` 和 `~/.hermes/AGENTS.md`

安装后重启对应客户端即可生效。

### 2.3 仅安装 Skill（不需要 Plugin/MCP）

```bash
./scripts/install-skill.sh --codex --yes
./scripts/install-skill.sh --claude --yes
./scripts/install-skill.sh --cc-switch --yes
```

### 2.4 验证接入

先在客户端中让模型记住一条偏好，例如：

```text
记住：我偏好本地优先、轻量、可控的技术方案。
```

然后提问：

```text
按我的偏好，PAM-OS 下一步应该怎么做？
```

成功接入时，模型应该先调用 `prepare_context`，读到相关偏好，再基于记忆上下文回答。

也可以通过命令行快速验证底层是否正常：

```bash
uv run --python 3.12 memory capture "我偏好本地优先、轻量、可控的技术方案。" --force
uv run --python 3.12 memory search "本地优先"
```

## 3. 插件架构：MCP + Skill

PAM-OS 接入大模型客户端时，职责拆成两层：

```text
MCP tools = 给模型稳定工具能力：prepare_context、capture_memory、search_memory 等
Skill     = 给模型操作策略：什么时候读记忆、什么时候写记忆、什么不要保存
```

Skill 负责"会判断"，MCP 负责"怎么调用"。当前推荐 `Plugin + MCP + Skill`：MCP 是日常优先工具入口，REST 和 CLI 保留为 fallback。

### 3.1 可用 MCP 工具

| 工具 | 说明 |
| --- | --- |
| `prepare_context` | 回答前准备记忆上下文。 |
| `capture_memory` | 回答后捕获稳定记忆。 |
| `record_behavior_choice` | 记录用户行为选择。 |
| `consolidate_memory` | 巩固画像。 |
| `get_profile` | 查看用户画像。 |
| `search_memory` | 搜索记忆。 |
| `inspect_memory` | 查看各表记忆明细。 |
| `get_storage_stats` | 查看存储概览。 |

### 3.2 Skill 触发场景

- 用户说"继续之前的项目""按我的偏好""记得我上次说的"等。
- 用户问题涉及长期目标、项目历史、历史决策、回答风格。
- 用户明确要求"记住这个"。
- 用户在多个选项中选择、拒绝或暂缓某些方案。

### 3.3 Fallback 机制

当 MCP 不可用时，skill 会读取安装目录下的 `config.toml` 选择 fallback：

```text
Codex:      ~/.codex/skills/pam-os-memory/config.toml
Claude:     ~/.claude/skills/pam-os-memory/config.toml
CC Switch:  ~/.config/cc-switch/skills/pam-os-memory/config.toml
```

默认是 `mode = "cli"`。如果要走 REST，把 `mode` 改成 `rest`，并确保 PAM-OS REST 服务已启动。

### 3.4 建议给模型的系统提示片段

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

## 4. 配置

复制示例配置：

```bash
cp config/pam-os.example.toml config/pam-os.toml
```

配置加载优先级为：

```text
CLI arguments > environment variables > config/pam-os.toml > built-in defaults
```

常用环境变量：

```bash
export PAM_OS_DB="/path/to/memory.sqlite3"
export PAM_OS_CONFIG="/path/to/pam-os.toml"
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
| `identity` | 用户明确声明的身份信息，例如姓名。 |
| `preference` | 用户偏好、倾向、喜欢或不喜欢。 |
| `goal` | 用户目标、计划、下一步。 |
| `project` | 项目上下文、技术决策、MVP 信息。 |
| `style` | 回答风格、语气、沟通偏好。 |
| `episodic` | 最近发生的具体事件。 |
| `semantic` | 一般事实或知识。 |

每条记忆包含 `content`、`importance`（0 到 1）、`confidence`（0 到 1）、`tags` 和 `valid_from`/`valid_to`。

### 5.3 Profile Evidence 和 Profile Trait

PAM-OS 不会把一次事件直接当作永久人格判断。画像层分两步：

```text
Extracted Memories / Behavior Events -> Profile Evidence -> Profile Traits
```

`ProfileEvidence` 是证据，说明系统为什么相信某个特征。`ProfileTrait` 是更稳定的用户画像。

### 5.4 Context Package

上下文包是给模型使用的最终文本。它会按类型分区（User Profile、Long-term Preferences、Active Projects 等），由 `prepare_context` 生成。

### 5.5 Policy Signal

Policy signal 是 PAM-OS 关于"什么时候应该使用记忆"的记忆。存储在 `policy_signals` 表中。`AdaptiveMemoryPolicy` 会先检查已学习的 policy signal，再回退到本地规则 provider。

## 6. 推荐工作流

通过插件接入后，模型会自动在合适的时机调用 MCP 工具。以下是推荐的循环：

```text
用户提问
  -> 调用 prepare_context
  -> 把 package.content 加入模型上下文
  -> 模型回答
  -> 如果用户或回答中出现稳定信息，调用 capture_memory
  -> 如果用户做出选择，调用 record_behavior_choice
  -> 周期性调用 consolidate_memory
```

**读记忆**（回答前）：当用户问题依赖个人偏好、长期目标、已有项目、历史决策或"继续之前的事"时，Skill 会引导模型调用 `prepare_context`。

**写记忆**（回答后）：当用户透露稳定信息时才写入（长期偏好、项目决策、风格要求、用户纠正等），跳过"哈哈好的"这类临时闲聊。

**记录行为选择**：当用户在多个方案中选择、拒绝或暂缓时，用 `record_behavior_choice` 记录。行为选择会进入 `behavior_events`，随后通过 consolidate 转成画像证据和画像特征。

**定期巩固画像**：定期调用 `consolidate_memory` 将近期记忆和行为事件提升为画像证据和画像特征。查看画像用 `get_profile`。

## 7. CLI 命令参考

插件接入后通常不需要直接使用 CLI。以下命令作为 fallback 和调试参考。

所有命令通过 `memory` 入口运行：

```bash
uv run --python 3.12 memory <command>
```

全局参数 `--config` 和 `--db` 需要写在子命令前：

```bash
uv run --python 3.12 memory --db .pam-os/demo.sqlite3 init
```

### 7.1 初始化

```bash
uv run --python 3.12 memory init
```

### 7.2 写入与搜索

```bash
# 低层写入（保存原始事件并抽取记忆）
uv run --python 3.12 memory add "我偏好 self-host 和本地可控系统。"

# 推荐写入（先判断是否值得保存）
uv run --python 3.12 memory capture "我决定 PAM-OS v0.1 先用 SQLite FTS5。" --force

# 搜索
uv run --python 3.12 memory search "self-host" --limit 5 --type preference
```

### 7.3 准备上下文

```bash
uv run --python 3.12 memory prepare "按我的偏好设计 PAM-OS 下一步"
uv run --python 3.12 memory prepare "继续做 PAM-OS" --force --json
```

### 7.4 行为选择与画像

```bash
uv run --python 3.12 memory behavior-choice \
  --context "PAM-OS 技术路线" \
  --chosen "SQLite FTS5" \
  --rejected "Qdrant" \
  --reason "MVP 阶段先保持本地、轻量、可控"

uv run --python 3.12 memory consolidate --recent 100
uv run --python 3.12 memory profile
uv run --python 3.12 memory profile --query "技术路线"
```

### 7.5 管理与检查

```bash
uv run --python 3.12 memory stats                    # 存储概览
uv run --python 3.12 memory inspect                  # 各表记忆明细
uv run --python 3.12 memory inspect --table memories --limit 10
uv run --python 3.12 memory reflect --recent 50      # 反思上下文
uv run --python 3.12 memory clear --confirm          # 清空所有数据（不可逆）
```

### 7.6 启动 REST 服务

```bash
uv run --python 3.12 --extra api memory serve --host 127.0.0.1 --port 8765
```

### 7.7 其他命令

```bash
uv run --python 3.12 memory should-use "Python list 怎么排序？"  # 判断是否需要读记忆
uv run --python 3.12 memory compile "继续做 PAM-OS"              # 低层上下文编译
```

## 8. REST API

当 MCP 不可用且配置了 REST fallback 时使用。启动服务：

```bash
uv run --python 3.12 --extra api memory serve --host 127.0.0.1 --port 8765
```

健康检查：`GET /health`。启动后 FastAPI 提供交互式文档：`http://127.0.0.1:8765/docs`。

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查、数据库路径、FTS 状态。 |
| `POST` | `/events` | 低层写入事件并抽取记忆。 |
| `GET` | `/memories/search?q=...` | 搜索记忆。 |
| `POST` | `/context/prepare` | 推荐的回答前上下文准备。 |
| `POST` | `/memory/capture` | 推荐的回答后记忆捕获。 |
| `POST` | `/behavior/choice` | 记录用户行为选择。 |
| `POST` | `/memory/consolidate` | 巩固画像。 |
| `GET` | `/profile` | 查看画像。 |
| `GET` | `/memory/inspect?table=all&limit=20&q=...` | 查看各表记忆明细。 |
| `POST` | `/context/compile` | 低层上下文编译。 |
| `POST` | `/reflect` | 最近记忆反思上下文。 |
| `GET` | `/storage/stats` | 查看存储概览。 |
| `POST` | `/memory/clear` | 清空所有记忆数据（需 `confirm: true`）。 |

## 9. Python API

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
| `capture_memory(content, ...)` | 推荐写路径，返回 `CaptureResult`。 |
| `record_behavior_choice(...)` | 记录用户行为选择。 |
| `consolidate_memory(...)` | 巩固画像。 |
| `get_user_profile(...)` | 读取画像。 |
| `compile_context(task, ...)` | 低层上下文编译。 |
| `reflect(recent=50)` | 从近期记忆编译反思上下文。 |
| `clear_memory()` | 清空所有记忆相关数据。 |
| `inspect_memory(table="all", limit=20, query=None)` | 查看各表记忆明细和统计。 |

## 10. 显式 JSON 记忆写入

规则抽取器支持直接输入 JSON 来精确控制类型、重要性、置信度和标签：

```bash
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

支持的 `type` 值：`semantic`、`episodic`、`identity`、`preference`、`goal`、`project`、`style`。

## 11. 数据存储

PAM-OS 使用 SQLite。默认数据库位于 `~/.pam-os/memory.sqlite3`，不同终端和不同项目共用同一份本机记忆库。初始化时创建的表：

| 表 | 说明 |
| --- | --- |
| `events` | 原始事件。 |
| `memories` | 抽取后的结构化记忆。 |
| `memories_fts` | FTS5 虚拟表。 |
| `memory_links` | 记忆之间的关系（当前 MVP 预留）。 |
| `context_packages` | 已生成的上下文包。 |
| `profile_evidence` | 用户画像证据。 |
| `profile_traits` | 稳定用户画像。 |
| `behavior_events` | 用户行为选择事件。 |
| `policy_signals` | 学习到的读/写/巩固/抑制记忆信号。 |

## 12. 检索和抽取规则

PAM-OS 的默认实现是本地规则版，读写路径通过 provider 接口组织：

- `MemoryPolicy`：判断当前任务是否应该读取或捕获记忆。
- `MemoryExtractor`：从事件中抽取结构化记忆。
- `MemoryRetriever`：检索候选记忆。
- `MemoryReranker`：在预算前重新排序候选结果。
- `ProfileConsolidator`：把记忆和行为证据提升为稳定画像。

默认 provider 位于 `pam_os.rule_provider`，`AdaptiveMemoryPolicy` 会先检查 `policy_signals`，再回退到规则策略。

当前默认抽取器是 `RuleBasedExtractor`：如果输入是 JSON 则按显式 JSON 抽取，否则按关键字推断记忆类型。检索会合并 SQLite FTS5 与 `LIKE` 查询结果并去重排序；当 FTS5 不可用时仍可通过 `LIKE` 工作。

## 13. 项目结构

```text
PAM-OS/
  config/
    pam-os.example.toml       示例配置
  eval/
    cases/                    记忆质量评估用例
  docs/
    design/                   设计文档
    usage.md                  本使用文档
  src/pam_os/
    cli.py                    CLI 入口
    runtime.py                核心运行时门面
    store.py                  SQLite 存储、检索、画像表操作
    providers.py              记忆策略、检索、重排、抽取、巩固接口
    adaptive_policy.py        学习到的 policy signal 与规则 fallback
    rule_provider.py          默认本地规则 provider
    extractor.py              规则抽取器
    orchestrator.py           provider pipeline 协调、预算、重排
    context.py                上下文编译器
    consolidator.py           默认画像巩固兼容封装
    quality.py                记忆质量评估器
    api.py                    REST API
    mcp.py                    MCP stdio server
    config.py                 配置加载
    models.py                 数据模型
  tests/
    test_runtime.py           端到端运行时测试
    test_mcp.py               MCP 协议与工具测试
    test_api_auth.py          REST 认证和清空接口测试
  pyproject.toml              包配置、命令入口、可选依赖
```

## 14. 开发和测试

```bash
uv run --python 3.12 --extra dev pytest                    # 运行全部测试
uv run --python 3.12 --extra dev pytest tests/test_runtime.py  # 运行时测试
uv run --python 3.12 memory --help                          # 查看 CLI 帮助
```

## 15. 质量评估与可观测性

PAM-OS 提供一个轻量的记忆质量评估闭环，用于验证读写策略、抽取、检索和画像巩固是否符合预期。默认评估用例位于 `eval/cases/`。

运行默认评估：

```bash
uv run --python 3.12 memory eval
```

输出 JSON：

```bash
uv run --python 3.12 memory eval --json
```

指定单个用例文件或目录：

```bash
uv run --python 3.12 memory eval --cases eval/cases/memory_quality_smoke.json
```

当前支持的评估类型：

| 类型 | 作用 |
| --- | --- |
| `read_policy` | 验证任务是否应该读取记忆。 |
| `capture_policy` | 验证内容是否应该写入长期记忆，以及抽取出的类型和内容。 |
| `extraction` | 验证原始事件抽取出的 memory type 和内容。 |
| `retrieval` | 验证查询能否召回目标记忆。 |
| `consolidation` | 验证记忆和行为证据能否巩固成预期画像。 |

`prepare_context`、`capture_memory` 和 `consolidate_memory` 会写入 `quality_traces` 表，记录 operation、stage、provider、decision、signals、related_ids 和 metrics。可以通过 inspect 查看：

```bash
uv run --python 3.12 memory inspect --table quality_traces --limit 20
```

这套机制的目标不是替代单元测试，而是给后续规则调整、LLM provider、embedding retriever 和 reranker 优化提供可回归的质量基线。

## 16. 常见问题

### 16.1 插件安装后不生效

重启对应客户端。检查 skill 文件是否在正确位置，MCP server 是否在客户端配置中注册。

### 16.2 `prepare_context` 没有返回上下文

该工具会先判断任务是否需要记忆。普通问题可能只返回决策结果。如需强制使用记忆，传入 `force: true`。

### 16.3 `capture_memory` 没有写入

该工具会跳过短暂内容（如"哈哈好的"）。要强制保存，传入 `force: true`。

### 16.4 搜索结果为空

可能原因：数据库路径不对（检查 `PAM_OS_DB` 和配置文件）、之前只保存了事件没抽取记忆、query 词和记忆内容差异太大。

### 16.5 REST 报依赖缺失

REST 需要 `--extra api`：

```bash
uv run --python 3.12 --extra api memory serve
```

### 16.6 配置文件没有生效

检查优先级：CLI arguments > environment variables > config/pam-os.toml > built-in defaults。如果设置了 `PAM_OS_DB`，它会覆盖 `[storage].db_path`。

## 17. 当前 MVP 边界

- 抽取器是规则版，不调用 LLM。
- 画像巩固也是规则版，主要覆盖偏好、回答风格、技术决策风格等有限模式。
- policy signal 目前通过本地规则和显式学习 API 使用，LLM teacher 仍是后续扩展。
- 检索是 SQLite FTS5 + LIKE 的本地混合检索，不包含向量数据库。
- `memory_links` 表已预留，但当前没有复杂图谱逻辑。
- 上下文预算按字符裁剪，不是精确 token 预算。
- 原始事件会保存；如需手动遗忘，可通过 `clear` 一次性清空全部记忆数据。

这些边界也是当前版本的设计取舍：先保持本地、轻量、可运行，后续可以在相同接口后面替换为 LLM 抽取器、向量检索或更复杂的画像巩固逻辑。
