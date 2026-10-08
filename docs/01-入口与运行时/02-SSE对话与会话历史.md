# SSE 对话与会话历史

`chat.py` 是浏览器和已经装配好的 LangGraph 图之间的流式桥：自己不调模型、不执行工具、不操作 Docker。它把一次 HTTP 请求接到 `session.agent.astream`，再把图吐出的 `values` / `custom` / `messages` 以及委派缓冲写成 SSE（一条长连接里按 `event:` 名字分块推数据）。`history.py` 管已经落库的会话目录、展示消息和删除。



---

## 1. 解决什么问题

多轮工具与子图要边跑边更新阶段、待办、工具名和委派条带。审批或补字段中断后本轮 HTTP 流结束，同一 `thread_id` 再 `resume`。历史页要会话列表和聊天正文；正文存在 `display_messages`，与 Checkpointer 里的图状态分开。

| 层 | 职责 |
|----|------|
| `POST /api/chat/stream` | 新消息开流；登记会话归属；返回 `StreamingResponse` |
| `POST .../resume` | 按归属用户 + `resume` 字典续跑同一生成器 |
| `stream_chat_response` | 锁环境 → `astream` → 译 SSE → 落展示/审计 |
| `GET .../state` / `.../history` | 是否仍中断；读展示消息 |
| `/api/history/*` | 会话目录、读消息、删四集合（不碰图） |

---

## 2. 架构 / 数据流

### 2.1 开流

```text
浏览器
  ↓
POST /api/chat/stream  → chat_stream
  → initialize；无 thread 则 generate_thread_id
  → 归属校验（已属他人 → 403）
  → save_conversation（先写归属，供 resume 查 user_id）
  → StreamingResponse(stream_chat_response) + X-Thread-Id
  ↓
get_session → run_lock.acquire → acquire_lease
bind_sandbox / bind_runtime / bind_dispatch_events
  ↓
yield thinking start
session.agent.astream(
  messages | Command(resume),
  stream_mode=["messages","values","custom"],
  subgraphs=True,
)
  ↓
每块先 drain 委派缓冲 → agent_dispatch
values  → phase / todos / interrupts（中断则落库 + done + return）
custom  → rubric_evaluation_* → phase / review_result
messages → tool_* / token
  ↓
Mongo：display_messages / harness_traces / dispatch_traces / conversations
  ↓
SSE done
finally：reset 三类 bind + release_lease + run_lock.release
```

`StreamingResponse` 跟着生成器每次 `yield` 立刻把一块 SSE 发给浏览器（`Cache-Control: no-cache`、`X-Accel-Buffering: no`）。

### 2.2 历史页

```text
GET  /api/history?user_id=...           → conversations 目录
GET  /api/history/{thread_id}/messages  → display_messages
DELETE /api/history/{thread_id}         → 删四份展示/轨迹文档
```

与 chat 侧 `GET /api/chat/{thread_id}/history` 读的是同一套 `display_messages`。

---

## 3. 核心设计与实现

### 3.1 SSE 协议与阶段文案

**`sse_event(event, data)`。** 拼 `event:` / `data:` 两行；data 用 `json.dumps(..., ensure_ascii=False)`。

| 事件 | 典型 payload | 何时发 |
|------|--------------|--------|
| `thinking` | `status: start\|end` | 开流动画；首次 token/tool 时 end |
| `phase` | `phase` + `label` | `state.phase` 变化，或 custom 评审开始 |
| `todo_update` | todos 列表或 tool 片段 | values 里 `todos` 变化；或 todo/task 类 ToolMessage |
| `token` | `content` + `source` | AI 纯文本；source = main / analyst / order |
| `tool_start` / `tool_args` / `tool_result` / `tool_end` | 名、参数片段、结果截断、id | messages 流工具块 |
| `agent_dispatch` | 委派 start/end | 每块前与正常结束前 `drain` |
| `review_result` | verdict / explanation / criteria / iteration | custom `rubric_evaluation_end` |
| `interrupt` | 类型 + 缺字段或审批载荷 | values 含 `interrupts` |
| `error` / `done` | 错误文案；`thread_id` + `interrupted` | 异常或流结束 |

**`PHASE_LABELS`：** planning / executing / reviewing / result / thinking → 前端展示文案。与 Harness YAML `phases.label`、中间件写入的 `phase` 字符串对齐（见 `03/02`）。

`subgraphs=True` 时每块是 `(namespace, chunk_type, chunk)` 三元组。`token.source` 只看 `namespace` 字符串是否含 `analyst` 或 `order`，否则 `main`。四个 YAML `name`（`task` 角色）与这三档 source 是两套标签。

### 3.2 `stream_chat_response`

参数：`message`、`thread_id`、`user_id` / `username`、可选 `resume_data`。

**准备输入**

| 模式 | display_messages | `astream` 输入 |
|------|------------------|----------------|
| 普通轮 | 加载已有 + append 本轮 user | `{"messages": [{"role":"user","content": message}]}` |
| resume | 只加载已有（不追加空 user） | `Command(resume=resume_data)` |

本地缓冲：`assistant_content`、`tool_calls_buffer`、`phase` / `last_phase`（去重）、`last_todos_sig`、`harness_trace`、`dispatch_trace`。

**环境绑定（`try` / `finally`）**

1. `session.run_lock.acquire()` — 同用户整轮流串行  
2. `sandbox_manager.acquire_lease(user_id)` — 本轮占用沙箱  
3. `bind_sandbox(user_id)` — ContextVar 稳定 Proxy  
4. `bind_runtime(user_id, agent_loader.store)` — 工具读用户/Store  
5. `bind_dispatch_events()` — 委派事件请求级缓冲  

`finally` 顺序：`reset_dispatch_events` → `reset_runtime` → `reset_sandbox` → 有 lease 则 `release_lease` → `run_lock.release`。生成器在 `try` 里 `return`（中断路径）也会先跑完 `finally`。

**每块处理顺序**

```text
drain → agent_dispatch
  ↓
chunk_type == values   → phase / todos / interrupts（可 return）
  → continue（本块不再进 messages）
chunk_type == custom   → reviewing / review_result → continue
chunk_type == messages → tool_* / token
```

**values。** `phase` 相对 `last_phase` 变化 → SSE `phase` + 记入 `harness_trace`。`todos` 签名变化 → `todo_update`（编成 `todo-{i}` 列表）。出现 `interrupts`：按 payload 推 `order_info_supplement` 或 `hitl_approval`；若有已累积 assistant 则写入 display；`save_display_messages` / `save_harness_trace` / `save_dispatch_trace`；`done(interrupted=True)` 后 `return`。

**custom。** `rubric_evaluation_start` → 阶段切 reviewing 并推 `phase`。`rubric_evaluation_end` → `review_result` + harness_trace 一条 review。

**messages。** `tool_call_chunks` → 结束 thinking，推 `tool_start` / `tool_args`，参数拼进 buffer。`type==tool` → 更新 buffer 状态，推 `tool_result`（内容截断 2000）/ `tool_end`；工具名含 todo/task 时可再推 `todo_update`。纯文本 AI → 累积 assistant，按 namespace 标 `source`，推 `token`。

**正常结束。** 追加 assistant 展示消息（含 `toolCalls`）；三份 save；有用户原文则用前 20 字更新会话标题；再 drain 一次 dispatch；`done(interrupted=False)`。异常：`error` + `done`。

### 3.3 HTTP：`/api/chat`

| 方法 | 路径 | 行为 |
|------|------|------|
| POST | `/stream` | `ChatRequest`：归属校验 → 先 `save_conversation` → `StreamingResponse(stream_chat_response)` |
| POST | `/{thread_id}/resume` | 查归属 `user_id`（缺省 `default_user`）→ 同一生成器，`resume_data=request.resume`，`message=""` |
| GET | `/{thread_id}/state` | `aget_state`；`state.next` 非空 → `interrupted: true` |
| GET | `/{thread_id}/history` | `get_display_messages` |

`/stream` 在已有归属与请求 `user_id` 不一致时 **403**。resume / state 用会话归属选 Session，保证落到建图时的用户沙箱与中间件闭包。

### 3.4 `api/history.py`

前缀 `/api/history`。薄封装 `agent_loader` 的展示层 CRUD，不 `astream`、不改 Checkpointer。

| 方法 | 路径 | 行为 |
|------|------|------|
| GET | `""` | `user_id` 查询参数（缺省 `default_user`）→ `{conversations}` |
| GET | `/{thread_id}/messages` | `{thread_id, messages}` |
| DELETE | `/{thread_id}` | `delete_conversation`（四集合）→ 成功 JSON |

图侧 checkpoint 是否仍在，见 `02/01` 工程边界。

---

## 4. 关键设计取舍

| 取舍 | 现行做法 |
|------|----------|
| 同用户并发 | `run_lock` 串行整轮 SSE；再加沙箱 lease |
| 展示 vs 图状态 | 历史页读 `display_messages`；续跑图读 Checkpointer |
| 中断控制路径 | values 里处理 interrupt：落库、结束本 HTTP，等 resume；本块 `continue` 不再按 token 解析 |
| 归属 | `/stream` 开流前写 conversations；resume 按 thread 反查 `user_id` |
| 观测 | harness / dispatch 与展示消息同轮落库，供事后审计 |

---

## 5. 工程边界

| 主题 | 现行行为 |
|------|----------|
| 开流即写归属 | `/stream` 在返回生成器前 `save_conversation`；interrupt 后 resume 能按 thread 找到 `user_id` |
| interrupt 落盘顺序 | 先 `save_*` 再 `done(interrupted=True)`；随后 GET history / state / resume 读到的是已写入数据 |
| 删除历史 | 清 UI/审计四集合；Saver 中该 `thread_id` 的图状态仍在 |
| `token.source` | namespace 子串归三档；与四个 `subagent_type` 名字不是一一映射 |
| 生成器 `return` | 中断路径 `return` 仍执行 `finally`，租约、锁、三类 ContextVar 都会解开 |
| 结果截断 | `tool_result` 内容约 2000 字；buffer 内 result 约 1000 字，控制 SSE 体积 |

---

## 6. 面试记忆点

**interrupt 之后前端做什么？**  
带同一 `thread_id` 调 `POST .../resume`，body 为审批或补字段的 `resume` 字典。

**chunk_type 为 values 时为什么 `continue`？**  
本块按图状态解释（阶段、待办、中断）。中断时已落库并结束本流；非中断也不再按 token / ToolMessage 解析同一块。

**`return` 之后 `finally` 会不会跑？**  
会。生成器在 `try` 里 `return` 前执行 `finally`。

**四个子 Agent 与 SSE 的 analyst / order / main？**  
四个是 YAML `name`，给 `task` 选角色。`token.source` 只看 namespace 是否含 `analyst` 或 `order`。

**`/stream` 和 history 删除各动哪层？**  
开流写归属与展示累积；history DELETE 只清四集合，不删 checkpoint。

**收束。** `chat.py` 是实时通信层：锁环境、启动 `astream`、把图输出译成 SSE 并写展示/轨迹。`history.py` 是展示层会话的列表、读取与删除。模型、工具、委派和 Harness 在图与中间件里。复习时先对节 2 时序与「每块顺序」，再对 interrupt / resume 与节 5 边界。
