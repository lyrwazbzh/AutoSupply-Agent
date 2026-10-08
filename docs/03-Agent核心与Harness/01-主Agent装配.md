# 主 Agent 装配

`create_main_agent` 把「一个用户」焊成可 `astream` 的编译图：模型、沙箱文件系统、工具、YAML 子 Agent、中间件、系统提示词。HTTP 侧 `AgentLoader` 按 `user_id` 缓存图；同一用户后续请求复用 Session，会话靠 `thread_id`。


---

## 1. 解决什么问题

一次对话需要 DeepSeek、用户容器、ERP（MCP）与本地工具、四个可委派角色，以及健康检查 / 记忆 / 委派门禁 / 评审。这些收在 `create_main_agent` 里焊成一张图，而不是每个请求临时拼。

| 层 | 职责 |
|----|------|
| `.env` → `env_utils` / `config` | LLM、Mongo、MCP、沙箱池、调用上限、`interrupt_on` |
| `bootstrap_sandbox` | 灌 `/workspace` 与 `/skills`；重建回调里再跑 |
| `CompositeBackend` | 默认沙箱；`/memories/`、`/persisted-skills/` 进 Store |
| `all_tools` | MCP 全量 + 本地袋（±记忆工具） |
| YAML → `subagents` | 四个角色规格 + 主提示委派协议文案 |
| 中间件栈 | 健康 → Harness → Context/WARM/Skills → task 门禁 → 记忆 → 熔断 → Rubric → 上限 |
| `create_deep_agent` | 焊 checkpointer / store，返回编译图 |
| `bind_runtime` | 每轮 SSE 给工具挂当前 `user_id` / Store |

四个旁路入口：`bootstrap_sandbox`、`_upload_project_to_sandbox`、`precompute_agent_context`（从 Store 填偏好与 WARM 摘要）、`create_main_agent`。Loader 建图时 Context 通常是 `ProcurementContext(user_id, username)`；运行期 WARM 由 `WarmMemoryMiddleware` 替换占位符。

---

## 2. 架构 / 数据流

```text
AgentLoader.get_session(user_id)
        │
        ▼
create_main_agent(user_context, checkpointer, store)
        │
        ├─ get_llm() + get_llm(thinking=False) → grader_llm
        ├─ 领沙箱 → Proxy → bootstrap → set_sandbox(Proxy)
        │     失败 → LocalShell；holder=None
        ├─ CompositeBackend(default=沙箱|LocalShell, ±Store 前缀)
        ├─ MCP + custom_tools → all_tools
        ├─ YAML → subagents + delegation_prompt
        ├─ 中间件列表（含重建回调）
        ├─ MAIN_SYSTEM_PROMPT.format + 可选记忆/委派/Skills 正文
        └─ create_deep_agent → AgentSession.agent
                │
                ▼
chat.py：bind_runtime → astream → reset_runtime
```

`.env` 经 `env_utils` 进入 `config` / `get_llm`。`bootstrap_sandbox` 在领到 Proxy 之后、以及健康检查重建回调里各跑一次。`_load_skills_prompt` 的结果只拼进系统提示词；`create_deep_agent(..., skills=None)`，沙箱内可执行文件靠 bootstrap 与 `SkillsSyncMiddleware`。

---

## 3. 核心设计与实现

### 3.1 环境、配置、日志

**`env_utils.py`。** import 时立刻 `load_env()`：从本文件上溯三级找仓库根 `.env`，有则 `load_dotenv(override=True)`，无则警告并继续。`get_env` / `get_env_int` 供 `config` 等读数；非整数字符串会 `ValueError`。

**`config.py`。** 装配用全局常数与建模型入口。

| 块 | 内容 |
|----|------|
| `get_llm(thinking=?)` | 共用模型名 / base_url / api_key / max_tokens / 重试。`thinking=True`（主对话）：开思考 + `reasoning_effort`。`thinking=False`（grader）：关思考、`temperature=0.1` |
| Mongo | URI、库名 |
| MCP | 服务根；SSE = 根 + `/sse` |
| 沙箱 | 镜像、工作目录/Skills/Memories 路径；温池、空闲超时、维护与健康检查间隔 |
| Store | `skills_store_namespace(user_id)` → `("persisted-skills", user_id)`；偏好命名空间前缀 |
| 上限 | 模型调用 50、工具调用 30；摘要阈值 `SUMMARIZATION_THRESHOLD=0.85` |
| HITL | `INTERRUPT_ON_TOOLS`：`order_create` / `order_update` / `rfq_create` / `sourcing_nominate`，允许 approve/reject |

**`log_utils.py`。** 五个预定义 logger（`agent` / `mcp` / `sandbox` / `web` / `middleware`），各最多一套 stdout + `JSONFormatter`（时间、级别、module、正文；有异常再附栈；输出为 dict 的 `str(...)`）。业务侧 import 变量，不各自 `basicConfig`。

### 3.2 装配相关类型：`schema.py`

| 类型 | 装配侧用法 |
|------|------------|
| `ProcurementContext` | 建图用户袋：`user_id` / `username`、`preferences`（**dict**）、`warm_memory`、`session_start`。Loader 通常只填 id 与用户名；`precompute_agent_context` 可填偏好与摘要 |
| `UserPreferences` | 偏好字段清单（格式/图表/货币/语言、最近供应商与查询）；写入 Store 时常落成 dict，Context 不强制嵌套该模型 |
| `ChatRequest` / `ResumeRequest` / `SSEEvent` | HTTP 边界；`thread_id` 空则上层生成 |
| `ConversationRecord` / `DisplayMessage` | 会话与展示文档字段约定 |

Harness 的 `Phase` / `Plan` / `ReviewResult` 见 `03/02`。Session 缓存后 `username` 是首次建图快照。

```text
前端 JSON → ChatRequest
  → user_id + username → ProcurementContext
  → thread_id → Checkpointer + 展示文档
偏好 Store dict → 可进 Context.preferences / WARM brief
```

### 3.3 沙箱灌装

**`_upload_project_to_sandbox`。** `mkdir -p /workspace/src` → 从 `PROJECT_ROOT` 收文件（跳过 `.git` / `__pycache__` / `node_modules` / `.env` / 密钥 / 图片等）→ gzip tar → `upload_files` 到 `/tmp/erp-agent-project.tar.gz` → 解压到 `/workspace/src` → 删包。只走 Proxy 公开的 `execute` / `upload_files`，换底层容器后仍可用。成功返回 `True`，异常 warning 后 `False`。

**`bootstrap_sandbox`。**

1. `mkdir` charts / output / data / python-packages / skills；`exit_code ≠ 0` → 抛错  
2. `_upload_project_to_sandbox`；`False` → 抛错  
3. `cp -r /workspace/src/src/skills/. /skills/`（tar 根是仓库根，解压目录是 `/workspace/src`，故路径含双层 `src`）；失败抛错  

领到 Proxy 后立刻跑；`SandboxHealthMiddleware` 重建回调 `_rehydrate_after_sandbox_rebuild` 再跑一遍，并 `invalidate` Skills 同步/恢复后立刻 `sync_now` / `restore_now`。图与 CompositeBackend 继续握同一 Proxy。

**`_load_skills_prompt(skills_dir)`。** 目录不存在 → `""`。收集全部 `SKILL.md` 与长度 > 20 的其它 `.md`；正则抽 `name` / `description` 做摘要；说明文字 + 摘要 + 全文拼进系统提示。

**`precompute_agent_context`（async）。** 无 Store → 空偏好、空 `warm_memory`。有 Store → `search(("user-preferences", user_id))` 合并 `key==preferences`；`MemoryKeeper` 做 legacy 迁移与 `build_warm_brief`，偏好仍空则 `load_preferences`；装进 `ProcurementContext`。生产 Loader 路径当前直接 `ProcurementContext(user_id, username)`，WARM 运行时由中间件刷新。

### 3.4 `create_main_agent`：七步焊图

无 context → 默认 `ProcurementContext()`。路径常量：`PROJECT_ROOT` = `__file__` 上溯三级；`SKILLS_DIR` = 仓库根 `src/skills`；`MEMORY_DIR` = 本包 `memory/`。

#### （1）LLM

`get_llm()` → 主模型；`get_llm(thinking=False)` → `grader_llm`（交给 `RubricMiddleware`）。

#### （2）Backend

| 条件 | 结果 |
|------|------|
| Docker / Manager 可用 | `get_sandbox(user_id)` → `SandboxBackendProxy` → `bootstrap` → `set_sandbox(Proxy)`；`managed_sandbox=True` |
| 不可用 | `LocalShellBackend(virtual_mode=True)`；`set_sandbox(None)`；`managed_sandbox=False` |
| `store` 非空 | 路由 `/memories/` → `(user_id,)`；`/persisted-skills/` → `skills_store_namespace(user_id)` |
| `store` 为空 | 仅 default（沙箱或 LocalShell） |

图、工具、Composite 全程握同一 Proxy；健康检查只换底层容器。

#### （3）工具

```text
mcp_tools = load_mcp_tools_sync()
custom_tools = [
  generate_chart, web_search, web_fetch, install_skill, list_user_skills,
  request_order_info, download_sandbox_file, list_sandbox_files,
  generate_document, generate_table_report,
]
memory_tools_enabled → + read_memory, remember
all_tools = mcp_tools + custom_tools
```

明细见 `05/01`、`06/01`、`07/01`。

#### （4）子 Agent

`load_subagent_configs` → `resolve_subagent_tools(configs, all_tools)` → `subagents`；`get_delegation_context_prompt` → 委派协议文案进系统提示。运行时主 Agent 调框架 `task`；门禁在 `TaskDispatchMiddleware`（见 `04/01`）。

#### （5）中间件

先读 Harness YAML 的 `review.max_iterations`（缺省 3）。造好 `SkillsSyncMiddleware`、`UserSkillsRestoreMiddleware`（有托管沙箱才传 Proxy），再建重建回调。按固定顺序装列表（见 §3.5）。

#### （6）系统提示

见 §3.6。

#### （7）`create_deep_agent`

| 参数 | 值 |
|------|-----|
| `model` / `tools` / `system_prompt` / `middleware` | 上步产物 |
| `subagents` | 空则 `None` |
| `skills` | `None`（正文进提示词；文件靠 sync） |
| `memory` | `[memory/AGENTS.md]` |
| `backend` | `composite_backend` |
| `interrupt_on` | `INTERRUPT_ON_TOOLS` |
| `checkpointer` / `store` | Loader 传入 |
| `name` | `procurement-main-agent` |

框架内部再加摘要、文件系统、Skills、SubAgent、Todo 等。返回编译图。

| 输入 | 结果 |
|------|------|
| Loader 传入 user_id、checkpointer、store | 该用户一张图；Docker 可用则已 bootstrap |
| 同一 user_id 再 `get_session` | 复用 Session，不再走本文件 |
| store 非空 | `/memories/`、`/persisted-skills/` 进 Store |
| 记忆工具开（缺省） | 工具池多 `read_memory`、`remember` |
| Docker 不可用 | LocalShell；holder 为 None；Skills/健康重建不拿 Proxy |

### 3.5 主图中间件栈

装栈顺序即运行顺序（`after_agent` 等钩子为逆序，见 `03/02`）：

```text
SandboxHealthMiddleware
→ HarnessPhaseMiddleware
→ ContextInjectionMiddleware
→ WarmMemoryMiddleware
→ SkillsSyncMiddleware
→ UserSkillsRestoreMiddleware
→ ToolsSummarizationMiddleware
→ TaskDispatchMiddleware
→ MemoryUpdateMiddleware
→ MemoryConsolidationMiddleware
→ SandboxCircuitBreakerMiddleware
→ RubricMiddleware(grader_llm, max_iterations)
→ ModelCallLimitMiddleware(50)
→ ToolCallLimitMiddleware(30)
```

| 中间件 | 行为摘要 |
|--------|----------|
| `SandboxHealthMiddleware` | 跑前探活。无 Manager/Proxy 直接过。间隔内且上次健康则跳过。通则 `touch`；连败达阈值 → `rebuild` → Proxy 热替换 → 重建回调（再 bootstrap + Skills 回填）→ 再 ping，失败整轮抛错 |
| `HarnessPhaseMiddleware` | `planning`、写/清 rubric、`executing`/`plan`、读评审写 `review_result`；打分打回在其后的 Rubric（见 `03/02`） |
| `ContextInjectionMiddleware` | 收下建图 `ProcurementContext` 为默认袋；`before_agent` 按 `thread_id` 取出打日志，返回 `None`，不改图 state。身份进提示词靠 `MAIN_SYSTEM_PROMPT.format` |
| `WarmMemoryMiddleware` | 调模型前从 Store 拉 WARM 摘要，替换系统消息里的 `WARM_MEMORY_SLOT`；无槽则追加一段 |
| `SkillsSyncMiddleware` | 跑前把仓库 `src/skills` 增量同步进 `/skills/`（相对路径哈希）。Proxy generation 变则先失效。无 Proxy 只校验本地 Skill 是否齐 |
| `UserSkillsRestoreMiddleware` | 跑前从 Store 用户 Skills 命名空间恢复到 `/skills/custom/...`；无 Store 或无 Proxy 空过 |
| `ToolsSummarizationMiddleware` | `messages` 条数 > 40 打 DEBUG；`self.tools = []`，不注册压缩工具。真压缩在框架摘要层 |
| `TaskDispatchMiddleware` | 只拦 `task`：门禁 → 补全 description → 超时执行 → 回流核验。MCP/沙箱工具不走这层 |
| `MemoryUpdateMiddleware` | 一轮结束后看本轮用户话起的消息，抽偏好合并进 WARM；无 Store 或抽不到则不动；异常吞掉 |
| `MemoryConsolidationMiddleware` | 同时机：规则摘要情节沉入 COLD（要有 `thread_id`），再遗忘扫描；不调 LLM |
| `SandboxCircuitBreakerMiddleware` | 拦 execute / run_code 等沙箱工具名；连败熔断后降级回复，MCP 不受影响；超时半开试探 |
| `RubricMiddleware` | state 有非空 `rubric` 才用 `grader_llm` 打分；`needs_revision` 且未到迭代上限则打回 |
| 调用上限 | 单次 run：模型 50、工具 30 |

**`context_injection.py` 补充。** 另有按 `thread_id` 的 `_context_store`（锁保护）。`update_context` / `get_current_context` / `clear_context` 供按请求换袋或清理。生产路径通常只走构造默认袋；工具读本轮用户/Store 走 `bind_runtime`，不走本中间件改消息。

**`tools_summarization.py` 补充。** 主图与子图配方都挂。框架摘要阈值用 `SUMMARIZATION_THRESHOLD`（0.85）；本钩子阈值是写死的条数 40，默认 INFO 级别下 DEBUG 行不进控制台。

### 3.6 系统提示词：`memory/prompts.py`

只存字符串。装配侧拼接顺序：

```text
MAIN_SYSTEM_PROMPT.format(
  user_id, username,
  preferences="以本次动态加载的记忆为准",
  warm_memory=WARM_MEMORY_SLOT,
)
  → 记忆工具开：+ MEMORY_USAGE_PROMPT
  → 有委派协议：+ delegation_prompt
  → _load_skills_prompt 非空：+ Skills 正文
```

**`MAIN_SYSTEM_PROMPT` 结构：** 身份（Harness 采购助手 → 整车制造采购与供应链）→ 当前用户 → WARM 记忆段 → 四阶段工作流 → 能力菜单 → 工作规范 → 交互风格。

四阶段是给模型看的软流程：问候/闲聊/简单问答直接答；要调工具或多步时才走 Planning（`write_todos`）→ Executing → Review（对照评审标准；打分/打回是 `RubricMiddleware`）→ Result。图状态里的 `phase` 由 `HarnessPhaseMiddleware` 写，提示词与 SSE 用同一套说法。

工作规范要点：单步查询主 Agent 自己调工具；`task` 在可并行 / 上下文隔离 / 调用链深任一成立时用，`subagent_type` 必须是四个 YAML 名，`description` 按 `input_context` 字段写键值行；工程与质量、HITL、补全项目工厂等约束；默认 Markdown、中文。硬门禁在 `TaskDispatchMiddleware` 与 `interrupt_on`。

**`MEMORY_USAGE_PROMPT`。** 说明 HOT / WARM / COLD：WARM 已有的别再问；提「上次」「之前」先 `read_memory`；说「记住」「默认」用 `remember`。

### 3.7 请求级 `runtime_context`

工具在建图时造好、多请求共用同一实例，不能把某个用户的 `user_id` / Store 闭包进工具对象。本模块用 `ContextVar`（每个 asyncio 任务一份值）挂本轮身份与 Store。

| API | 行为 |
|-----|------|
| `bind_runtime(user_id, store)` | 写入两个 ContextVar，返回一对 Token |
| `reset_runtime(tokens)` | 恢复到 bind 之前 |
| `get_current_user_id` / `get_current_store` | 工具侧现取；缺省用户 `default_user`，Store 缺省 `None` |

`chat.py` 在 `astream` 前 bind，在 `finally`（正常结束、中断返回、异常）里 reset。读方包括记忆工具、`web_fetch` 装 Skill 时的写入、`list_user_skills` 等。

```text
图级：user_id → Session / 沙箱 / Store namespace / 建图 Context
请求级：bind_runtime → 工具 get_current_*
会话级：thread_id → Checkpointer + 展示文档
```

### 3.8 子 Agent 中间件配方：`middleware_config.py`

给子 Agent 配中间件列表的工厂，自己不跑图。`SKILLS_DIR` 与主装配同一棵 `src/skills`。

**`get_analyst_middleware` / `get_order_middleware`。** 种类与顺序相同，五层：

| 层 | 作用 |
|----|------|
| `SummarizationToolMiddleware`（框架） | 挂 `compact_conversation`，长上下文时可主动压缩 |
| `ContextInjectionMiddleware` | 分析侧缺省用户名「采购分析师」，订单侧「采购订单专员」 |
| `SkillsSyncMiddleware(skills_dir=...)` | 只传目录、不传 Proxy → 校验本地 Skill 是否齐，不往容器写文件 |
| `ToolsSummarizationMiddleware` | 条数 > 40 的 DEBUG 探针 |
| `SandboxCircuitBreakerMiddleware(3, 60s)` | 沙箱工具熔断；MCP 不受影响 |

**`get_all_subagent_middlewares`。** 按四个 YAML `name` 做成字典：`supply-planning-analyst`、`supplier-quality-risk` → analyst；`delivery-collaboration`、`strategic-sourcing` → order。与 `task(subagent_type=...)` 名字一致。

主图中间件由 `create_main_agent` 自拼。本模块产出的字典接到建图逻辑、并被 `create_deep_agent(..., subagents=...)` / 框架读入规格上的 middleware 后，才进运行中的子图。

---

## 4. 关键设计取舍

| 取舍 | 现行做法 |
|------|----------|
| 沙箱引用稳定 | holder 登记 **Proxy**；健康检查只换底层容器，图与 CompositeBackend 引用不变 |
| Skills 进模型与进容器 | 正文 `_load_skills_prompt` 进提示词；文件 `SkillsSyncMiddleware` 同步；`skills=None` |
| Store 隔离 | `/memories/`、`/persisted-skills/` 按 `user_id` 分 namespace |
| 身份两层 | 图级 Session 缓存 `ProcurementContext`；请求级工具用 `ContextVar` |
| grader 与主模型 | 主模型开思考；grader 关思考 + YAML `max_iterations` |
| 子图中间件 | 独立五层配方（压缩 + Context + Skills 校验 + 探针 + 熔断），轻于主图全栈 |

---

## 5. 工程边界

| 主题 | 现行行为 |
|------|----------|
| LocalShell 回退 | holder 为 `None`；依赖 Docker 的健康重建 / Skills 写容器不绑 Proxy；沙箱工具拿到空句柄时各工具按自身分支处理 |
| Context 按 thread 更新 | 需调用方走 `update_context`；生产 Loader 路径通常只用建图默认袋 |
| 摘要探针可见性 | `ToolsSummarizationMiddleware` 打 DEBUG；默认 INFO 下控制台看不到 |
| SSE 阶段文案 | YAML `phases.label` 与 `chat.py` 的 `PHASE_LABELS` 对齐后前端才显示对应标签 |
| `precompute` vs Loader | `precompute_agent_context` 可预填偏好与 WARM；Loader `_build_agent_for_user` 当前只构造 id/用户名，WARM 靠运行时中间件 |
| 子图 middleware 字典 | `get_all_subagent_middlewares` 产出配方；是否挂上以 subagents 规格与框架读取为准 |

---

## 6. 面试记忆点

**CompositeBackend 三条路径？**  
默认进沙箱（或 LocalShell）；`/memories/` → `(user_id,)`；`/persisted-skills/` → `("persisted-skills", user_id)`。

**主模型与 grader 的差别？**  
主模型 `get_llm()` 开思考；grader `get_llm(thinking=False)`；迭代次数来自 YAML `review.max_iterations`。

**工具怎么知道当前用户？**  
`chat` 开流 `bind_runtime`；记忆/技能等工具 `get_current_*`；流结束 `reset_runtime`。

**`thread_id` 和 `user_id`？**  
`user_id` 选 Session、沙箱、Store namespace；`thread_id` 选 checkpoint 与展示文档。

**Context 中间件和 `bind_runtime` 各管什么？**  
中间件构造时收下建图 Context，`before_agent` 按 thread 取出打日志。本轮工具读写用户/Store 用 `bind_runtime`。

**Skills 为什么 `skills=None`？**  
提示词侧手动加载正文；沙箱侧 Sync/Restore；框架 `skills` 参数不传。

**收束。** 对象按 `user_id` → Context/沙箱 → Proxy → CompositeBackend → `all_tools` → YAML 子 Agent → 中间件闭包 → 提示词 → `create_deep_agent` 焊成用户级图。HTTP 只 `bind_runtime` 后 `astream`。复习时先对节 2 时序与 §3.4 七步，再对 §3.5 栈序与 §3.7 两层身份。阶段与 rubric 见下一篇。
