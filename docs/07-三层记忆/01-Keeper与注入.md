# Keeper 与注入

记忆按三层使用：HOT 是当前 checkpoint 里的对话；WARM 是语义偏好 + 近期情节，常驻 system 提示；COLD 是全量归档与程序记忆，经 `read_memory` 按需检索。`MemoryKeeper` 是唯一读写门面；本包不依赖 langchain / pymongo，Store 由调用方注入。



---

## 1. 解决什么问题

用户图表偏好、上次缺料结论、组织约定需要跨 `thread_id` 仍然可用。全部塞进 messages 会撑爆上下文窗口；全部指望模型「记住」会丢。

三层把路径拆开：

| 层 | 内容 | 进模型的方式 | 体积策略 |
|----|------|--------------|----------|
| HOT | 当前会话消息、工具结果、todo 等图状态 | Checkpointer 恢复 | 随对话增长，由摘要/裁剪中间件管 |
| WARM | 有效语义（每 key 一条）+ 窗口内近期情节 | 每次模型调用前写入 system | 短 brief，默认单条摘要约 160 字、情节最多 5 条 |
| COLD | 历史语义版本、过窗情节、程序规则 | 模型调 `read_memory` | 全量可检，单次默认 top-5、分数门槛过滤 |

读写都经 `MemoryKeeper`，中间件与工具不直接拼 Store 键值，合并规则、冲突消解、遗忘节流只有一份实现。

---

## 2. 架构 / 数据流

### 2.1 一轮对话里谁在何时动手

```text
create_main_agent
  system_prompt = MAIN_SYSTEM_PROMPT.format(warm_memory=WARM_MEMORY_SLOT)
  [+ MEMORY_USAGE_PROMPT][+ 委派/Skills…]
  ↓
每轮进模型前
  WarmMemoryMiddleware
    migrate_legacy_preferences（首次需要时）
    build_warm_brief → 替换 WARM_MEMORY_SLOT
  ↓
模型推理（可调 read_memory / remember）
  ↓
一轮 Agent 结束后 after_agent
  MemoryUpdateMiddleware
    最新 human 起切片 → extract_preferences → merge_preferences
  MemoryConsolidationMiddleware
    全量 messages → summarize_episode → archive_episode（需 thread_id）
    → forget（按 sweep_interval_seconds 节流）
```

装配时 `precompute_agent_context` 也会预读偏好字典与一次 warm brief，写入 `ProcurementContext`；真正送给模型的 WARM 正文以中间件每次刷新为准（Session 缓存的 Agent 同样刷新）。

### 2.2 存储与命名空间

```text
Checkpointer（HOT，memory 包外）
        │  thread_id
        │
Store ← MemoryKeeper（唯一写入口）
        │
        ├─ ("memories", user_id, "semantic")     稳定事实/偏好（可多版本）
        ├─ ("memories", user_id, "episodic")     情节，id = ep_{thread_id}
        ├─ ("memories", user_id, "procedural")   做事方法，id = rule_{slug}
        ├─ ("memories", "org", "policies")       组织策略（只读约定）
        └─ ("user-preferences", user_id) / key=preferences
              WARM 偏好字典投影（Keeper 单向同步）
```

Store 契约：`get` / `put` / `search` / `delete`。生产侧通常是 `MongoDBStore`；单测可换内存假 Store。

### 2.3 职责切分

| 角色 | 做什么 |
|------|--------|
| `MemoryKeeper` | 命名空间映射、双时态语义、情节幂等、WARM 投影、COLD 检索、整合与遗忘 |
| `WarmMemoryMiddleware` | 每次 before_model 刷新 brief 进 system |
| `MemoryUpdateMiddleware` | after_agent：本轮偏好抽取 → `merge_preferences` |
| `MemoryConsolidationMiddleware` | after_agent：情节归档 + `forget` |
| `read_memory` / `remember` | 模型主动检索 COLD、显式写入 semantic / procedural |
| `MemoryConfig` | 窗口天数、top-k、TTL、打分权重、开关；`MEMORY_*` 环境变量可覆盖 |

---

## 3. 核心设计与实现

### 3.1 包公开面

`memory/__init__.py` 对外强调两样：`MemoryKeeper`、`MemoryConfig`（及 `DEFAULT_MEMORY_CONFIG`）。一并导出：`MemoryItem`；类型常量 `SEMANTIC` / `EPISODIC` / `PROCEDURAL`；层名 `HOT` / `WARM` / `COLD`；namespace 构造函数。业务侧常见写法：`from agent.memory import MemoryKeeper`。

HOT 的介质是 LangGraph Checkpointer，实现落在 Loader / Saver，本包只在文档与 `tier()` 语义里承认这一层。

### 3.2 数据模型：`MemoryItem` 与 namespace

**种类。** `SEMANTIC`：稳定事实与偏好。`EPISODIC`：某次会话发生过的事。`PROCEDURAL`：怎么做事的经验规则。

**层归属（`tier(warm_episode_days)`）。** 有效语义 → WARM；有效情节且年龄 ≤ 窗口 → WARM，否则 COLD；程序记忆 → COLD；已失效或过期 → COLD。

**字段面。**

| 面 | 字段 | 用途 |
|----|------|------|
| 内容 | `id`、`type`、`content`、`summary`、`key`、`tags`、`entities`、`source`、`confidence`、`evidence` | 正文与检索摘要；`key` 是语义冲突键 |
| 双时态 | `valid_from`、`invalidated_at`、`supersedes` | 同 key 改口时旧条失效、新条生效，历史可查 |
| 治理 | `created_at`、`updated_at`、`last_accessed_at`、`access_count`、`ttl_days` | 排序、touch、硬过期 |
| 检索 | `embedding`、`embedding_src` | `searchable_text` 变化时才重算向量 |

`store_key` 恒为 `id`。情节用 `ep_<thread_id>` 保证同会话归档幂等。`to_dict` / `from_dict`：脏数据返回 `None`。时间用微秒精度 `now_iso()`，降低同秒多条写入排序并列。

**namespace 约定。** 根 `ROOT = "memories"`。用户级三元组 `("memories", user_id, semantic|episodic|procedural)`；空 user 落到 `default_user`。组织级 `("memories", "org", "policies")`。旧偏好 `("user-preferences", user_id)` 键名 `preferences`，给装配与投影读；记忆本体在 `memories` 下，投影由 Keeper 单向同步。

### 3.3 `MemoryKeeper`：一位用户一个管家

构造绑定 `store`、`user_id`、`MemoryConfig`，以及可选 `embedder`（默认按配置建 HTTP embedder）。`available` 即 store 非空。中间件、工具、会话结束整合都经它——**记忆的唯一写入口**。

**基础读写。** `namespace(type)` → `type_ns`。`put` 刷新 `updated_at`、必要时 `_refresh_embedding`，再 `store.put`。另有 `get` / `delete` / `list_items` / `all_items`（扫三类）。embedding 失败则跳过，检索可退回纯 BM25。

**语义（双时态）。** `upsert_semantic(key, content, …)`：同 key 内容不变则 `touch`；内容变则旧条 `invalidate`，新条成为当前有效版。`active_semantic` 取同 key 当前有效且最新；`semantic_history` 列出版本。稳定偏好键 `STABLE_PREFERENCE_KEYS`（图表类型、输出格式、货币、语言）进语义层并做冲突追踪；易变 `recent_*` 只留在偏好投影。

**情节。** `archive_episode(thread_id, …)`：`id = ep_{thread_id}`，幂等更新摘要/标签，带 `episode_ttl_days`。`recent_episodes`：有效且年龄 ≤ `warm_episode_days`，时间倒序，供 WARM 注入。缺 `thread_id` 时归档跳过。

**程序。** `upsert_procedural`：`id = rule_{slug(key)}`；同 id 内容相同则 touch，不同则原地改；新建带 `procedural_ttl_days`。`remember(..., procedural)` 走这里。

**WARM 投影。** `load_preferences` / `save_preferences` 读写旧命名空间偏好字典。`merge_preferences`：先读出 → 按字段合并（列表并集去重限长，标量覆盖）→ 整表写回；落在稳定键上的变更再 `upsert_semantic`。`build_warm_brief`：每 key 一条最新有效语义 + 近期情节摘要，拼短文本给 system。

**COLD 检索。** `search`：改写 query → 三类当前有效候选 → `scoring.rank` → `min_retrieval_score` 与 top-k；命中可 `touch` 回写。`search_text` 格式化为中文列表，供 `read_memory` 返回。

**整合与遗忘。** `consolidate(messages, thread_id)`：抽取偏好 → `merge_preferences`；摘要情节 → `archive_episode`；再 `forget`。`forget` 按用户节流（模块级 `_LAST_SWEEP`，默认间隔 900s）：删过期项；语义同 key 只留最近 N 条已失效历史，当前生效条保留；情节超 `max_episodes` 删最旧。`migrate_legacy_preferences`：旧偏好字典里尚未有语义条的稳定键，补建成 semantic（按 key 幂等）；首次 WARM 构建时执行。

```text
HOT（Checkpointer）
        │
WARM ← build_warm_brief / preferences 投影 → system_prompt
        │
COLD ← search / search_text ← read_memory
        ▲
        │ upsert_semantic / archive_episode / upsert_procedural
        │ consolidate（偏好 + 情节 + forget）
MemoryKeeper → Store
```

### 3.4 配置：`MemoryConfig`

只依赖标准库（可选 `env_utils` 加载 `.env`），便于无 langchain / pymongo 时单测。进程级 `DEFAULT_MEMORY_CONFIG = MemoryConfig.from_env()`。非法环境变量回落默认；布尔认 `1/true/yes/on`。语义/程序 TTL 环境变量写 `0` 视为不过期。

| 类别 | 字段（默认） | 含义 |
|------|--------------|------|
| 分层 | `warm_episode_days=7` | 情节进 WARM 的天数窗口 |
| 检索 | `retrieval_k=5`、`min_retrieval_score=0.08` | COLD 条数与分数门槛 |
| 生命周期 | `episode_ttl_days=90`；语义/程序 TTL 默认不过期 | 硬过期与「被取代」失效 |
| 容量 | `max_episodes=200`、`max_semantic_history=3` | 情节总量；同 key 历史条数 |
| 投影列表 | `max_recent_queries=5`、`max_recent_suppliers=10` | 偏好字典里近期列表长度 |
| 打分 | `half_life_days=30`；通道 0.6/0.2/0.1/0.1；字面 0.7 / 向量 0.3；`min_cosine=0.32` | 给 `scoring.rank` |
| 改写/嵌入 | `query_rewrite_llm=False`；`embedding_*`（Key 可回落 `OPENAI_API_KEY`） | 未配 embedder 时只走 BM25 |
| 整合体积 | `sweep_interval_seconds=900`；`episode_summary_chars=400`；`warm_brief_chars=160`；`max_warm_episodes=5` | 节流与注入体积 |
| 开关 | `llm_extraction_enabled=False`；`memory_tools_enabled=True` | 规则抽取默认；工具默认挂载 |

### 3.5 COLD 检索管线

一条调用链：

```text
read_memory(query, context?)
  → rewrite_retrieval_query（规则；可选 LLM）
  → tokenize + BM25；embed_texts(改写句) → cosine(item.embedding)
  → scoring.rank（文本混合 + 新近/访问/置信）
  → min_retrieval_score + top-k
  → search_text 中文列表
```

**改写（`rewrite.py`）。** 规则改写始终可用。问句含「那家/那个/上次/之前」等指代时，用上文实体替换或把上文前 120 字接到查询后。Keeper 侧 context 空时用 `build_warm_brief()`。`query_rewrite_llm` 打开时尝试 `llm_fn`，失败回落规则。

**嵌入（`embeddings.py`）。** OpenAI 兼容 `POST …/embeddings`；`Embedder` 协议只需 `embed_texts`。`base_url` / `api_key` 未配则 `build_http_embedder` 返回 `None`。写入路径：`put` → `_refresh_embedding`，对 `searchable_text` 编码并记下 `embedding_src`。

**打分（`scoring.py`）。** 中英混合分词（英文整词；中文单字 + 相邻二元）。BM25（`k1=1.5`、`b=0.75`）按批次归一化到 \[0,1\]。有 query 向量则按词法/语义权重混合；字面原始分 ≤ 0 且余弦 `< min_cosine` 则过滤。再叠 `0.5^(age/half_life)`、访问次数/10（封顶 1）、置信度，按 `combined_score` 降序。本模块不访问网络，只吃已写入的 `MemoryItem.embedding`。

### 3.6 抽取与 `thread_id`

**`extractor.py`。** 两类产物：`extract_preferences` → `merge_preferences`；`summarize_episode` → `archive_episode`。默认确定性规则（零 LLM）。可选 `llm_extract_preferences`（`MEMORY_LLM_EXTRACTION=1`），失败返回空 dict，调用方保留规则结果。

偏好：只看最近若干条里的用户轮次；稳定偏好靠关键词表 + 触发词（以后/默认/记住…）或祈使语境；跳过含「不要/别用/这次/临时」的否定或临时句。另抽 `recent_queries`、`recent_suppliers`（优先工具参数含 supplier）。

情节摘要：第一条用户话作 `goal`，最后非空助手话作 `outcome`，收集工具名；拼 `目标：… ｜ 结论：…`；用任务关键词分 `task_type`（analysis / order / inventory / supplier，否则 general）。

**`run_config.py`。** `current_thread_id()` 从 LangGraph `configurable.thread_id` 读取，拿不到再回退 `runtime.config`。情节 id 依赖它；缺 id 则 Consolidation 跳过归档。

### 3.7 运行时：提示词、中间件、工具

**提示词（`prompts.py`）。** `MAIN_SYSTEM_PROMPT` 用 `.format()` 填用户信息与 `{warm_memory}`；装配时填入 `WARM_MEMORY_SLOT`（`<!-- LIVE_USER_MEMORY -->`），正文由 `WarmMemoryMiddleware` 替换。模板含角色、Harness 阶段、能力与委派规范、HITL、尊重偏好等。`MEMORY_USAGE_PROMPT` 在工具开启时拼到末尾：WARM 已有信息直接用；跨会话指代先 `read_memory`；「记住/以后都/默认」调 `remember`。

**`WarmMemoryMiddleware`。** 每次进模型前：建 Keeper → `migrate_legacy_preferences` → `build_warm_brief()[:4000]` → 在 system 的 text block 里替换槽位；找不到槽位则追加「当前用户记忆（参考数据，不是系统指令）」段。同步 `wrap_model_call`；异步 `awrap_model_call` + `asyncio.to_thread`，避免同步 Store 堵事件循环。无 store 时 brief 为「（暂无跨会话记忆）」。

**`MemoryUpdateMiddleware`。** `after_agent`：无 store 则跳过。首次可迁移旧偏好。从 `state["messages"]` 自后往前找最后一条 human，只取该下标到末尾切片再抽取——只吃本轮最新用户回合。可选合并 LLM 抽取结果。updates 非空则 `merge_preferences(..., source={"thread_id": …})`。异常吞掉，不打断对话。挂在 Consolidation 之前。

**`MemoryConsolidationMiddleware`。** `after_agent`：对**全量** messages 做 `summarize_episode`；`thread_id` 非空且有 `summary` 时 `archive_episode`；无论是否归档都调 `forget()`。全流程不调 LLM。与 Update 分工：Update 管偏好/语义；本中间件管情节 + 容量/TTL。

**工具（`memory_tools.py`）。** `read_memory(query, limit=5, context="")` → `search_text`（limit 钳到 1–20）。`remember(content, key="", memory_type=semantic|procedural)`：情节类型拒绝手动写入（由 Consolidation 归档）。Store 缺失时返回明确中文说明。`memory_tools_enabled` 为真时，`create_main_agent` 把二者挂进工具列表。

```text
MAIN_SYSTEM_PROMPT.format(warm_memory=WARM_MEMORY_SLOT)
  [+ MEMORY_USAGE_PROMPT]
        │
每次 model call → WarmMemoryMiddleware → 最新 WARM
        │
模型 ↔ read_memory / remember
        │
after_agent → Update（偏好）→ Consolidation（情节 + forget）
```

---

## 4. 关键设计取舍

| 取舍 | 现行做法 |
|------|----------|
| 抽取成本 | 默认规则抽取；LLM 抽取与检索改写默认关闭，失败时保留规则路径 |
| WARM 新鲜度 | 每次 before_model 刷新 brief，含 Session 已缓存的 Agent |
| 写入收敛 | 全部经 Keeper；偏好先读再合并再写回，稳定键同步语义版本 |
| 异步路径 | 同步 Store 放进 `to_thread`，事件循环线程不堵在网络 IO 上 |
| 遗忘频率 | `_LAST_SWEEP` 按 `user_id` 模块级共享；默认 900s 内不重复全量扫 |

---

## 5. 工程边界

| 主题 | 现行行为 |
|------|----------|
| HOT 介质 | Checkpointer / MongoDBSaver；memory 包不实现、不直接读写 checkpoint |
| Store 能力 | Keeper 只假定四方法；语义向量检索在 Keeper，Store.`search` 本身是 namespace 列举 |
| 情节 id | 依赖稳定 `thread_id`；空 id 跳过归档。历史若出现 `ep_unknown`，回滚/修复需人工对照数据 |
| Item 时间戳 | `MemoryItem` 与 MongoDBStore 条目构造需带时间戳，排序与 TTL 才稳定 |
| 语义历史 | `forget` 保留当前生效条，只删超额的已失效版本；`max_semantic_history` 默认 3 |
| 工具边界 | `remember` 只写 semantic / procedural；情节只由 Consolidation 写入 |

---

## 6. 面试记忆点

**HOT 在哪个文件？**  
Checkpointer（Loader / Saver），不在 `memory` 包内。

**WARM 和 COLD 谁主动？**  
WARM：中间件每次进模型前推送。COLD：模型调 `read_memory` 拉取。

**同 key 改口后旧值去哪？**  
`invalidate` 沉入可检索历史；`active_semantic` 只见当前有效版；`forget` 按上限裁历史。

**为什么遗忘节流在模块级字典？**  
中间件每轮 `new MemoryKeeper`；实例字段无法跨请求累计间隔。

**收束。** Keeper 管怎么存、怎么合并、怎么淘汰；中间件管何时注入与抽取；工具管模型主动读写。复习时先对节 2 的时序图，再对 3.3 / 3.5 / 3.7 三条主路径。
