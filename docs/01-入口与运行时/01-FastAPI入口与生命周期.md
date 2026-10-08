# FastAPI 入口与生命周期

`web_main.py` 造出可服务的 FastAPI `app`：挂 CORS、注册 chat / history 路由、提供健康检查与生成文件下载。启动时预热沙箱温池并拉起后台维护循环；停止时置 `stop_event`、取消维护任务、关掉 Motor。进程级装配与单次 `astream` 分开。


---

## 1. 解决什么问题

浏览器要跨源打到服务端口，图表/文档落盘后要能 HTTP 取回，空闲沙箱要在后台回收并补齐温池。这些属于**进程一生**的装配；对话怎么接到图、怎么推 SSE，在 chat 路由里完成。

| 层 | 职责 |
|----|------|
| `lifespan` | 预热温池、起/停维护任务、关 Motor |
| `_sandbox_maintenance` | 周期 `cleanup_idle` + `ensure_warm_pool`（线程池） |
| CORS + routers | 跨源；挂上 `/api/chat`、`/api/history` |
| 本文件直挂路由 | `/`、`/health`、`/api/download/{filename}` |
| `web_config` | Motor 惰性客户端；与 PyMongo Saver/Store 同库不同客户端 |

---

## 2. 架构 / 数据流

```text
uvicorn 加载 web_main.app
  ├─ lifespan
  │    to_thread(ensure_warm_pool)     # 失败只打日志，不挡 listen
  │    create_task(_sandbox_maintenance)
  │    yield                           # 对外服务
  │    finally：
  │      stop_event.set
  │      cancel 维护任务
  │      close_mongo_client
  │      （不销毁已认领容器；user→container 映射可恢复）
  ├─ CORSMiddleware（origins=*，开发）
  ├─ include_router chat / history
  └─ GET / 、 /health 、 /api/download/{filename}
```

`DOWNLOAD_DIR` = `Path(__file__).resolve().parent.parent / "download"` → 即 `src/download`（不存在则 `mkdir`）。

维护循环与请求路径的探活分工：

```text
后台维护（本文件）
  → cleanup_idle_sandboxes
  → ensure_warm_pool
  （不调用 health_check_all）

请求路径 SandboxHealthMiddleware（见 08 / 03）
  → ping / 连败 rebuild
  → Proxy 热替换 + bootstrap / Skills 回填
```

---

## 3. 核心设计与实现

### 3.1 `web_main.py`：应用本体

**路径准备。** 启动时把仓库根塞进 `sys.path`（本文件上溯两级），保证以本文件启动时也能 import 到 `src` 包。

**`app`。** `FastAPI(..., lifespan=lifespan)`，title / description / version 为采购助手 API 元数据。

**中间件。** `CORSMiddleware`：`allow_origins=["*"]`，credentials / methods / headers 全开（开发向）。

**路由挂载。**

| 来源 | 前缀 / 路径 | 作用 |
|------|-------------|------|
| `chat_router` | `/api/chat` | SSE 对话、resume、state、该 thread 展示消息（见 `01/02`） |
| `history_router` | `/api/history` | 会话列表、读消息、删展示/轨迹四集合（见 `01/02`、`02/01`） |
| 本文件 | `GET /` | 简单欢迎 JSON + version |
| 本文件 | `GET /health` | `{"status":"ok"}` |
| 本文件 | `GET /api/download/{filename}` | 只从 `DOWNLOAD_DIR` 取普通文件；不存在 → 404；否则 `FileResponse`（`application/octet-stream`） |

**`__main__`。** `uvicorn.run(app, host="0.0.0.0", port=8000)`。

### 3.2 生命周期：`lifespan` 与维护循环

**启动（`yield` 前）。**

1. 建 `asyncio.Event` 作为 `stop_event`
2. `await asyncio.to_thread(sandbox_manager.ensure_warm_pool)` — 预热失败不阻止 Web 起来；首请求仍可按需建沙箱或退 LocalShell
3. `asyncio.create_task(_sandbox_maintenance(stop_event), name="sandbox-maintenance")`

**关闭（`finally`）。**

1. `stop_event.set()` — 唤醒卡在 `wait_for` 上的维护循环  
2. `maintenance_task.cancel()`，吞掉 `CancelledError` 后 await  
3. `await close_mongo_client()`  
4. 不在此处销毁已认领容器：Manager 持久化 user→container，进程重启后可恢复映射（细节见 `08/01`）

**`_sandbox_maintenance`。**

```text
while not stop_event:
  to_thread(cleanup_idle_sandboxes)
  to_thread(ensure_warm_pool)
  单轮异常 → warning，继续下一轮
  wait_for(stop_event.wait, timeout=SANDBOX_MAINTENANCE_INTERVAL_SECONDS)
    → 超时：进入下一轮
    → stop 已 set：退出循环
```

间隔默认来自 `config.SANDBOX_MAINTENANCE_INTERVAL_SECONDS`（环境可读，缺省 60）。Docker / Manager 的阻塞调用一律 `to_thread`，避免堵事件循环。停机用 Event + `wait_for`，可在间隔内立刻被 `set` 唤醒，再配合 `cancel` 收束任务。

### 3.3 `web_config.py`：Motor

给 FastAPI 协程侧用的异步 Mongo（展示集合、会话列表、traces）。URI / 库名经 `env_utils`：缺省 `mongodb://localhost:27017`、`erp_agent`。与 `agent/config` 及 Loader 里 PyMongo 的 Saver / Store **同库、不同客户端**：一套异步 CRUD，一套同步 LangGraph。

| API | 行为 |
|-----|------|
| `get_mongo_client` | 惰性建全局 `AsyncIOMotorClient`；已有则复用 |
| `get_db` | 在该客户端上取 `MONGODB_DB_NAME`，供 `agent_loader` 展示 CRUD |
| `close_mongo_client` | `close` 并清空全局引用；仅 `lifespan` shutdown 调用 |

```text
.env → MONGODB_URI / MONGODB_DB_NAME
get_db() → Motor 库句柄 → Loader conversations / display_messages / traces
shutdown → close_mongo_client
```

Loader 何时建 PyMongo Saver/Store，见 `02/01`；首请求 `get_session` 时初始化，与本文件启动预热沙箱是两条线。

### 3.4 与下游模块的边界

| 本文件负责 | 下游负责 |
|------------|----------|
| 造 app、CORS、挂 router、养池、关 Motor | chat：锁环境、`astream`、SSE、落展示（`01/02`） |
| download 只读 `src/download` | 工具侧把产物落到该目录或经沙箱下载链路（`06/01`） |
| 维护：idle 回收 + 补温池 | HealthMiddleware：探活、rebuild、Proxy 热替换（`08/01`） |

---

## 4. 关键设计取舍

| 取舍 | 现行做法 |
|------|----------|
| 预热与可用性 | 预热失败只打日志，进程照样 listen |
| 维护 vs 探活 | 后台只做 idle/温池；全量 health 重建留在请求中间件，避免 Agent 仍握旧后端 |
| 阻塞 I/O | Docker/Manager 调用进 `to_thread` |
| 停机唤醒 | `asyncio.Event` + `wait_for` 超时，可立刻打断间隔等待 |
| 容器生命周期 | shutdown 不销毁已认领容器，依赖 Manager 映射恢复 |
| Mongo 双客户端 | Motor 给 HTTP；PyMongo 给 LangGraph Store/Saver |

---

## 5. 工程边界

| 主题 | 现行行为 |
|------|----------|
| 预热失败 | 异常不向上阻断 `yield`；服务已 listen，首请求按需建沙箱或 LocalShell |
| 维护单轮失败 | warning 后继续循环，不取消任务 |
| 下载路径 | `DOWNLOAD_DIR / filename`；要求 `exists` 且 `is_file`；依赖路径参数与目录约束，额外规范化有限 |
| CORS | 开发配置 origins=`*`；生产需按部署收紧时改本文件中间件参数 |
| Motor 关闭时机 | 仅 lifespan `finally`；进程被强杀时依赖 OS 收连接 |

---

## 6. 面试记忆点

**Motor 和 pymongo 为什么两套？**  
FastAPI 协程用 Motor；LangGraph Store/Saver 接口是同步的，用 pymongo。同 URI / 库名。

**停机谁负责关 Mongo？**  
`lifespan` 的 `finally` 调 `close_mongo_client`。

**后台维护做什么、不做什么？**  
做 idle 回收与补温池。探活重建与 Proxy 热替换在请求路径的 `SandboxHealthMiddleware`。

**预热失败服务还能起来吗？**  
能。预热在 try 里失败不挡 listen；首请求再按需领沙箱。

**`/api/download` 读哪？**  
固定 `src/download` 下的普通文件，供图表等生成物 HTTP 取回。

**收束。** 入口很薄：造 app、开 CORS、挂路由、养沙箱池、关 Motor。会话怎么接到 Agent 见 `01/02` 与 `02/01`；温池与五态见 `08/01`。复习时先对节 2 的 lifespan 树与「维护 vs Health」分工。
