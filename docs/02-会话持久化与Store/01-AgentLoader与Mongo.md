# AgentLoader 与 Mongo

`AgentLoader` 管本进程共享的 Checkpointer / Store，并按 `user_id` 缓存可 `astream` 的用户级图。同一套 Mongo 上再分三条账本：图状态（Saver）、跨会话 KV（`langgraph_store`）、展示与审计（Motor 四集合）。模块末尾导出全局 `agent_loader`；类上 `__new__` 再做一层进程内单例。

代码：`src/api_view/agent_loader.py`、`mongodb_store.py`；Motor 入口 `web_config.get_db`。SSE 消费见 `01/02`；图装配见 `03/01`；记忆 namespace 与检索见 `07/01`；委派审计事件见 `04/01`。

运行时读的是 `_sessions[user_id].agent`。`self.agent` 仅在 `user_id == "default_user"` 时写入，给旧调试脚本用。

---

## 1. 解决什么问题

多用户并发时，不能共用同一张编译图（沙箱 Proxy、中间件闭包都绑着用户）。又要刷新后接着聊、跨会话保留偏好/技能/记忆，还要给前端会话列表与聊天正文。Loader 把「进程内图缓存」和「Mongo 三条账本」焊在一起。

| 层 | 粒度 | 存哪 | 谁写谁读 |
|----|------|------|----------|
| Checkpointer | 一个 `thread_id` 的图状态（消息、phase、interrupt） | `MongoDBSaver`（PyMongo） | LangGraph `astream` / `aget_state` |
| Store | 跨 thread 的 `(namespace, key)`（偏好 / 技能 / 记忆） | `langgraph_store`（`MongoDBStore`） | 中间件、记忆工具、`bind_runtime` 读方 |
| 展示与审计 | 一个 `thread_id` 的 UI / 时间线 | Motor：`conversations`、`display_messages`、`harness_traces`、`dispatch_traces` | `chat.py` / `history.py` 经 Loader CRUD |

每个用户有独立 `AgentSession`、`run_lock`、建图时的 `ProcurementContext`。偏好、技能、记忆共用同一个 Store，靠含 `user_id` 的 namespace 隔离。LangGraph 持久化与展示 CRUD 共用同一 Mongo URI / 库名，分别使用 PyMongo 与 Motor（两套连接池）。

---

## 2. 架构 / 数据流

### 2.1 请求侧

```text
HTTP（chat / history / resume）
        │
        ▼
agent_loader.get_session(user_id)
        │
        ├─ _ensure_resources → MongoDBSaver + MongoDBStore
        └─ 缓存未命中 → to_thread(_build_agent_for_user)
                → create_main_agent(checkpointer, store)
                → AgentSession(agent, run_lock)
        │
        ▼
create_config(thread_id, user_id)
        │
        ▼
session.agent.astream / aget_state
        │
        ▼
Motor：display_messages / conversations / harness_traces / dispatch_traces
```

### 2.2 Store 侧

```text
Memory / Skill / Preference
        │
        ▼
store.put / get / search / delete
        │
        ▼
文档 _id = namespace 用 :: 拼接 + :: + key
        │
        ▼
集合 langgraph_store
```

### 2.3 数据 Scope

```text
Process（一个 Python 进程 / 一个 uvicorn worker）
│
├─ AgentLoader 单例
│     _sessions / _resources_lock / _sessions_lock / _session_build_locks
├─ MongoDBSaver 引用（共享 PyMongo client）
├─ MongoDBStore 引用（自建 PyMongo client）
│
├─ user u1 → AgentSession：compiled graph + run_lock + username 快照
└─ user u2 → AgentSession：…

MongoDB（跨进程）
│
├─ Checkpoints（Saver 管理）
│     thread t1 / thread t2
├─ langgraph_store
│     ("user-preferences", u1)
│     ("persisted-skills", u1)
│     记忆 namespace（含 user_id 与类型段，见 07）
└─ UI / 审计
      conversations / display_messages
      harness_traces / dispatch_traces
```

| 数据 | Scope | 存储 |
|------|-------|------|
| Graph State | thread | Checkpointer |
| Memory / Skill / Preference | user + namespace | `langgraph_store` |
| AgentSession | user + **本进程** | `_sessions` 内存 |
| Chat Display / 审计 | thread | Motor 四集合 |
| `run_lock` | user + **本进程** | `AgentSession` |

---

## 3. 核心设计与实现

### 3.1 `AgentSession` 与单例

**`AgentSession`（dataclass）。** 一个用户一份：`user_id`、`username`、编译好的 `agent`、串行 `run_lock`（同用户两路 SSE 在本进程内互斥跑图）。

**`AgentLoader`。** `__new__` + `_initialized` 保证只构造一次。实例字段：`_checkpointer`、`_store`、`_mongo_client`、`_sessions`、三把锁相关结构。模块级 `agent_loader = AgentLoader()` 供全 API 引用。

### 3.2 共享资源：`_ensure_resources`

```text
_store 已有 → 直接返回
否则拿 _resources_lock 双检
  → to_thread(_initialize_resources_sync)
      PyMongo MongoClient(MONGODB_URI)
      → MongoDBSaver(mongo_client)
      → MongoDBStore(uri, db_name, collection_name="langgraph_store")
失败 → 抛错（建图路径不可用）
```

Saver 与 Store 都连同一 URI / 库；Saver 复用 `_mongo_client`，Store 内部再开一个 `MongoClient`（`serverSelectionTimeoutMS=5000`）。阻塞 I/O 放在线程池，避免卡住事件循环的初始化路径。

**`initialize(user_id=None)`。** 兼容旧调用：只保证共享资源就绪；若带了 `user_id` 再预建 Session。

### 3.3 `get_session`：按用户建图与缓存

缓存键只有 `user_id`。

1. `await _ensure_resources()`
2. 在 `_sessions_lock` 下查缓存；命中直接返回
3. 未命中：为该用户取或建 `_session_build_locks[user_id]`，释放 sessions 锁后进入建图锁
4. 建图锁内再双检缓存（避免并发重复建图）
5. `asyncio.to_thread(_build_agent_for_user)`：`ProcurementContext(user_id, username)` + 共享 checkpointer/store → `create_main_agent`
6. 写入 `AgentSession`；弹出该用户的 build_lock；`default_user` 时同步写 `self.agent`

`username` 是首次建图快照：之后同 `user_id` 换名仍复用旧 Session 与旧 Context 闭包。运行期工具身份靠 `bind_runtime`（见 `03/01`）。

```text
同 user_id
  → 复用 Session / 图 / run_lock
同用户新 thread_id
  → 新 checkpoint 文档 + 新展示文档；图对象不变
```

### 3.4 运行配置与展示 / 审计 CRUD

**`create_config(thread_id, user_id)`** → `{"configurable": {"thread_id", "user_id"}}`，交给 LangGraph。

**`generate_thread_id`** → UUID 字符串。

展示与审计一律 `get_db()`（Motor，异步库 `MONGODB_DB_NAME`）：

| API | 集合 | 行为 |
|-----|------|------|
| `save_display_messages` / `get_display_messages` | `display_messages` | 按 `thread_id` upsert / 读 `messages` 列表 |
| `save_conversation` / `get_conversations` | `conversations` | upsert 元数据；列表按 `user_id` + `updated_at` 倒序 |
| `get_conversation_user_id` | `conversations` | resume/state 时查会话归属，选对用户 Session |
| `delete_conversation` | 四集合 | 删该 `thread_id` 的 conversations、display_messages、harness_traces、dispatch_traces |
| `save_harness_trace` | `harness_traces` | 阶段流转时间线（chat 在流中写入） |
| `save_dispatch_trace` / `get_dispatch_trace` | `dispatch_traces` | `task` 委派 start/end 事件 |

正文在 `display_messages`，与 Checkpointer 里的图消息是两套数据；历史页读展示层，续跑图读 Saver。

### 3.5 `MongoDBStore`：`BaseStore` 的 Mongo 实现

同步 PyMongo 接口给框架；`aget` / `aput` / `asearch` / `adelete` / `alist_namespaces` / `abatch` 直接委托同步实现。

**文档形状**

| 字段 | 含义 |
|------|------|
| `_id` | `namespace` 各段用 `::` 拼接，再 `::` + `key` |
| `namespace` | 字符串数组 |
| `key` | 项键 |
| `value` | JSON 兼容值（`_serialize_value`：标量/dict/list；其它转 `str`） |
| `created_at` / `updated_at` | ISO 字符串；`put` upsert 时首次插入才写 `created_at` |

索引：唯一 `(namespace, key)`；另有 `updated_at`。

**`_make_item`。** 构造 LangGraph `Item`：优先带 `created_at` / `updated_at`；旧版 `Item` 不接受时间戳字段时退回三参构造。时间解析失败用当前时间。

**CRUD**

| 方法 | 行为 |
|------|------|
| `get` / `put` / `delete` | 按文档 `_id` 读写删；`put` upsert |
| `search` | 按 namespace **前缀**匹配；可选 `filter` 落到 `value.字段`；按 `updated_at` 倒序，支持 limit/offset |
| `list_namespaces` | 扫文档收集 namespace 集合，可按前缀、截断深度 |
| `batch` / `abatch` | 按 op 类型分发 get/put/search/delete |
| `close` | 关 Store 自己的客户端 |

**前缀查询 `_namespace_prefix_query`。** `namespace` 存成数组，查询写成 `namespace.0`、`namespace.1`… 逐段相等，保证 `("persisted-skills", user_id)` 一类隔离可查。

**`query` 参数。** 签名兼容 `BaseStore` 的语义检索接口；本实现不做向量检索，参数接受后丢弃。语义检索在 `MemoryKeeper`（见 `07/01`）。

```text
Loader 建一份 MongoDBStore
  → 焊进各用户 create_main_agent
  → Warm / Skills / remember 等经同一 store 实例读写
```

---

## 4. 关键设计取舍

| 取舍 | 现行做法 |
|------|----------|
| 图按用户缓存 | `create_main_agent` 成本高；同 `user_id` 复用图，对话用 `thread_id` 分叉 |
| 三账本同库 | Checkpointer / Store / UI 共用 URI；协议上 Saver+Store 用 PyMongo，展示用 Motor |
| Store 同步内核 | 对齐 LangGraph `BaseStore`；async 方法薄包装同步调用 |
| 用户隔离 | Session 键 `user_id`；Store 靠 namespace 含 `user_id`；`search` 前缀逐段匹配 |
| 建图并发 | per-user `build_lock` + 双检，避免同用户打出两张图 |

---

## 5. 工程边界

| 主题 | 现行行为 |
|------|----------|
| Store 异步接口 | `await store.aget()` 等仍走同步 PyMongo 网络 IO，占用调用该协程的事件循环线程。初始化路径用了 `to_thread`；Store CRUD 未再包一层 `to_thread` |
| Session 生命周期 | `_sessions` 只增不淘汰：无 TTL、无 LRU。每个 Session 持有 compiled graph 与 `run_lock`；用户数随进程寿命累积 |
| 进程边界 | Loader、`_sessions`、锁、`run_lock` 都是**单进程**状态。`uvicorn --workers N` 得到 N 份 Loader；同一 `user_id` 可有 N 份 Session。跨进程串行只靠 Mongo 上的 Checkpointer / Store |
| 展示删除 vs 图状态 | `delete_conversation` 清 UI/审计四集合。Saver 中该 `thread_id` 的 checkpoint 仍在；同一编号仍可 `astream` / `aget_state` 接到旧图状态 |
| `username` | 首次建图快照；请求级新名字不刷新已缓存 Session |
| `search(query=)` | namespace 前缀列举 + 可选 `value` 精确过滤，不是信息检索 |
| 两套（实为多套）Client | Saver 一份 PyMongo；Store 自建一份 PyMongo；Motor 服务 FastAPI CRUD |

---

## 6. 面试记忆点

**Checkpointer 和 Store 各存什么？**  
Checkpointer：一个 thread 的图怎么往下跑。Store：跨 thread 的 `(namespace, key)`。

**Session 为什么按 `user_id` 缓存？**  
`create_main_agent` 含中间件与工具列表。同用户复用图对象；对话用 `thread_id`。

**`thread_id` 和 `user_id` 怎么分工？**  
`user_id` 选 Session、沙箱身份、Store namespace。`thread_id` 选 checkpoint 与展示文档。

**技能 / 偏好怎样按用户隔开？**  
`("persisted-skills", user_id)`、`("user-preferences", user_id)`（记忆段见 07）。`search` 写成 `namespace.0`、`namespace.1` 相等。

**`run_lock` 保证到哪一层？**  
保证本进程内同一用户两路 SSE 串行。多 worker 时每进程一把锁。

**展示消息和图消息？**  
前端读 `display_messages`；续跑图读 Checkpointer。删会话清前者，不自动清后者。

**收束。** Loader 管本进程的 Session 与共享 Saver/Store 引用；Mongo 管跨进程的图状态、跨 thread 键值、UI/审计集合。复习时先对 Scope 图与三账本表，再对 `get_session` 双检与节 5 边界。
