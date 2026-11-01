根据 review，迁移计划需要做三处根本调整：

- 认证、租户隔离提前到第一阶段。
- `RuntimeContext` 不再写入 Graph State，而是通过 DeepAgents `context_schema/context` 注入。
- 共享 Agent 放到第六阶段；前五阶段先完成隔离、租约和安全恢复。

下面是修订后的正式迁移计划。

# 生产架构迁移计划 v2

## 目标架构

```text
认证网关
  ↓ 可信身份
RequestContext Loader
  ├─ tenant/user/roles/permissions
  ├─ 本次偏好与 WARM Memory 快照
  ├─ request_id/run_id/thread_id
  └─ 请求级依赖
  ↓
共享 Agent Graph
  ├─ RuntimeContext：本次运行依赖，不进入 Checkpoint
  ├─ Graph State：任务和工作流状态，可恢复
  ├─ PostgreSQL Store：记忆与长期数据
  ├─ PostgreSQL Checkpointer：会话执行状态
  ├─ Sandbox Lease：运行期间动态获取
  └─ WriteAudit：ERP 外部副作用状态
```

## 阶段 0：依赖与构造期状态审计

这一阶段不改变运行行为，先明确所有用户状态绑定点。

### 工作内容

1. 固定 DeepAgents、LangChain、LangGraph 精确版本。
2. 验证当前版本的：
   - `context_schema`
   - `context`
   - 子 Agent runtime/context 继承
   - 自定义 Backend 获取 runtime 的方式
3. 扫描所有构造期用户状态：
   - `user_id`
   - 用户偏好和记忆
   - Store namespace
   - ERP 凭证
   - Sandbox Proxy
   - 子 Agent middleware
   - 后台任务和回调
4. 建立共享 Agent 禁止项：
   - Agent 构造函数不能接收具体用户。
   - 静态 System Prompt 不能包含私人数据。
   - 工具和中间件不能把用户身份保存在实例字段中。
   - 全局变量不能保存当前请求身份。

项目当前使用 `deepagents>=0.7,<0.8`，生产前应锁定精确版本，避免上下文和子 Agent 行为随依赖更新变化。

### 主要检查文件

- [`main_agent.py`](<D:/Autumn recruitment/Agent-Harness-main/src/agent/main_agent.py:260>)
- [`agent_loader.py`](<D:/Autumn recruitment/Agent-Harness-main/src/api_view/agent_loader.py:26>)
- [`runtime_context.py`](<D:/Autumn recruitment/Agent-Harness-main/src/agent/runtime_context.py:1>)
- [`sandbox_holder.py`](<D:/Autumn recruitment/Agent-Harness-main/src/agent/backends/sandbox_holder.py:1>)

### 验收条件

形成完整清单，能够回答每一个用户相关字段是在构造期、请求期还是持久化层读取。

---

# 阶段 1：可信请求上下文与租户隔离

共享 Agent之前，先确保身份不可伪造、资源归属不可绕过。

## 1.1 定义 RuntimeContext

新增类型化运行上下文：

```python
class AgentRuntimeContext:
    tenant_id: str
    user_id: str
    username: str
    roles: tuple[str, ...]
    permissions: frozenset[str]

    request_id: str
    run_id: str
    thread_id: str

    preferences: dict
    warm_memory: str
```

其中：

- `request_id`：本次 HTTP 请求，每次 resume 都重新生成。
- `run_id`：一次 Agent 工作流运行。
- `thread_id`：持续存在的会话。
- `operation_id`：不放在 RuntimeContext 顶层，由具体 ERP 写操作生成并进入业务状态。

通过 DeepAgents 的 `context_schema` 注册，在调用时传入：

```python
agent.astream(
    input=...,
    context=runtime_context,
    config={"configurable": {"thread_id": thread_id}},
)
```

## 1.2 明确数据边界

| 数据 | 保存位置 |
|---|---|
| 当前身份、权限、request_id、run_id | RuntimeContext |
| 当前沙箱租约、连接引用 | RuntimeContext/运行时服务 |
| messages、plan、intent、phase | Graph State |
| 待审批 operation_id | Graph State + PostgreSQL |
| 偏好、长期记忆 | PostgreSQL Store |
| 会话归属 | PostgreSQL |
| 写审计、对账任务 | PostgreSQL audit schema |

不得把完整 RuntimeContext 写进 Graph State，避免 resume 使用旧权限和旧沙箱租约。

## 1.3 身份与租户

- 生产环境禁用 `AUTH_MODE=none`。
- `tenant_id/user_id/roles/permissions` 只能来自认证网关或已验证 JWT。
- 忽略请求体中的 `user_id`。
- conversation、message、audit、memory、sandbox 表增加 `tenant_id`。
- 所有资源查询使用 `tenant_id + user_id`。
- resume、history、delete、state 全部验证会话归属。

### 验收条件

- 伪造 `user_id` 无法访问他人会话。
- 只知道 `thread_id` 不能读取、恢复或删除会话。
- 跨租户访问在进入 Agent 前被拒绝。
- Checkpoint 中不保存权限和沙箱租约。

---

# 阶段 2：中间件请求级动态化

这一阶段保留现有 Middleware 体系，只移除构造期用户状态。

## 2.1 重写 ContextInjectionMiddleware

删除：

- `_default_context`
- `_context_store`
- `update_context()`
- 进程内 thread/context 映射

新的职责：

1. 从 `runtime.context` 读取安全上下文。
2. 将用户名、偏好和 WARM Memory 快照动态加入 System Prompt。
3. 不把身份权限复制进 Graph State。
4. 不在每次模型调用时查询 PostgreSQL。

请求开始和 HITL resume 时加载一次偏好与 WARM Memory，当前运行期间使用快照。

## 2.2 动态化有状态中间件

需要修改：

- `HarnessPhaseMiddleware`
- `WarmMemoryMiddleware`
- `MemoryUpdateMiddleware`
- `MemoryConsolidationMiddleware`
- `ERPWriteMiddleware`
- `UserSkillsRestoreMiddleware`
- `SandboxHealthMiddleware`
- `ResultAuditor`

从：

```python
self.user_id = user_id
```

改成：

```python
user_id = runtime.context.user_id
tenant_id = runtime.context.tenant_id
```

无用户状态的中间件不改，例如：

- 模型调用次数限制
- 工具调用次数限制
- 固定 Rubric 配置
- 通用摘要逻辑

### 验收条件

- 同一个 Middleware 实例可以交替处理两个用户。
- 两个用户并发运行时，日志、记忆、审计中不发生身份串扰。
- 新请求能够读取更新后的偏好。
- 一次运行中不反复查询 WARM Memory。

---

# 阶段 3：工具、子 Agent 与审批隔离

## 3.1 Store namespace 动态化

删除构造期闭包：

```python
namespace=lambda _: (user_context.user_id,)
```

改成从 runtime 获取：

```text
tenant_id / user_id / memory_type
tenant_id / user_id / persisted-skills
tenant_id / user_id / shortage-records
```

## 3.2 子 Agent可信上下文

主 Agent委派提示词只传：

- 任务目标
- 已提取业务字段
- 已有业务对象
- 输出要求

不能把提示词中的 `user_id` 当作可信身份。

子 Agent调用工具时必须使用同一个 RuntimeContext。需要分别验证：

- 声明式子 Agent
- 已编译子图
- 后续可能出现的远程子 Agent

如果框架不能自动继承，则由子 Agent适配层显式传递 runtime context。

## 3.3 工具层权限校验

以下操作必须在服务端校验权限：

- MCP ERP 查询
- ERP 写操作
- 业务知识检索
- 用户 Skill
- 沙箱文件访问
- 审批与 resume

不能依赖模型判断“当前用户是否有权限”。

## 3.4 统一审批策略

建立独立的 `ApprovalPolicyRegistry`，统一生成：

- 主 Agent `interrupt_on`
- 子 Agent `interrupt_on`
- WriteAudit 的 `requires_approval`
- 前端审批描述
- 审批权限要求

保证：

```text
一份策略
两条调用路径
一个 operation_id
一次持久化审批
```

同时处理当前问题：

- 删除主 Agent重复 HITL 注册。
- 删除独立的 `INTERRUPT_ON_TOOLS`。
- `edit` 未实现前从审批决策中移除。
- resume 决策必须绑定明确的 `operation_id`，不能只按顺序匹配。

### 验收条件

- 主 Agent直调写工具只触发一次审批。
- 子 Agent调用同一工具也只触发一次审批。
- 子 Agent无法绕过权限、审计和审批。
- 两条路径生成一致的 `operation_id/payload_hash/policy_id`。

---

# 阶段 4：沙箱运行时化

## 4.1 RuntimeSandboxBackend

Agent Graph只持有稳定的运行时 Backend：

```text
RuntimeSandboxBackend
    ↓ runtime.context
SandboxLeaseService
    ↓
当前请求的实际 Sandbox Proxy
```

不再在 `create_main_agent()` 中为某个用户获取并绑定沙箱。

## 4.2 PostgreSQL 沙箱租约

沙箱租约至少包含：

```text
tenant_id
user_id
sandbox_id
node_id
lease_owner
lease_token
lease_expires_at
heartbeat_at
generation
status
```

关键规则：

- 获取和续租使用数据库原子条件更新。
- generation 变化后旧租约立即失效。
- 执行者提交结果前验证 lease token/generation。
- `ContextVar` 只作为当前协程快速访问方式，不作为租约真实性来源。

## 4.3 文件隔离

工作目录调整为：

```text
/workspaces/{tenant_id}/{user_id}/{thread_id}/
```

Backend 层负责：

- 路径归一化
- 拒绝 `..`
- 拒绝越过当前 workspace 的绝对路径
- 符号链接逃逸检查
- 写入目录白名单

## 4.4 HITL 行为

发生人工审批中断时：

1. 保存 Checkpoint 和 operation 状态。
2. 释放沙箱租约。
3. 不长期持有数据库锁。
4. resume 时重新认证。
5. 获取新沙箱租约。
6. 检查 generation。
7. 必要时重新同步 Skill 和运行文件。

需要专门验证 ContextVar 在以下路径的传播：

- `asyncio` 任务
- `asyncio.to_thread`
- 线程池
- SSE 后台任务
- 子 Agent
- 沙箱重建回调

无法保证传播时显式传递 context。

### 验收条件

- 两个用户无法访问彼此文件。
- 同一用户不同 thread 使用独立工作目录。
- 租约失效的旧执行者不能继续写沙箱。
- HITL 暂停期间不占用沙箱租约。
- 沙箱重建后旧 Proxy/旧 generation 不再生效。

---

# 阶段 5：会话并发、Checkpoint 与写恢复

## 5.1 会话运行租约

使用 PostgreSQL 持久化租约，不同时引入 Redis 和 Advisory Lock。

建议表：

```text
app.session_run_leases
- tenant_id
- thread_id
- run_id
- lease_token
- owner_node
- expires_at
- heartbeat_at
- generation
```

作用：

- 同一个 thread 同时只能存在一个有效 Graph Run。
- 普通请求与 resume 不能并发。
- 不持有长事务或数据库连接。
- 旧执行者失去 lease 后不能提交最终状态。

## 5.2 三层并发控制

三种并发必须分开处理：

1. 会话并发：session lease。
2. 沙箱并发：workspace 隔离和 sandbox lease。
3. ERP 业务并发：ERP 版本号、业务幂等和条件更新。

Agent会话锁不能保证订单或库存一致性。

## 5.3 消息持久化

当前展示消息采用整段 JSONB 读改写，取消用户锁后可能丢更新。

建议改为逐条追加：

```text
app.messages
- message_id
- tenant_id
- thread_id
- run_id
- sequence
- role
- content
- tool_calls
- created_at
```

如果暂时保留 JSONB，则必须增加 `version` 并使用乐观锁。

## 5.4 安全 resume 链路

恢复顺序固定为：

```text
重新认证
  ↓
验证 tenant/user/thread 归属
  ↓
获取 session lease
  ↓
读取 Checkpoint
  ↓
生成新的 request_id/run_id
  ↓
验证待审批 operation_id
  ↓
查询 ERP 写操作状态
  ↓
获取新的 sandbox lease
  ↓
安全恢复
```

写状态处理：

| 写操作状态 | 恢复行为 |
|---|---|
| `SUCCEEDED` | 返回已成功结果，禁止重写 |
| `RECONCILED_SUCCEEDED` | 返回对账结果，禁止重写 |
| `PENDING_APPROVAL` | 等待合法审批 |
| `APPROVED` 且未派发 | 允许继续派发 |
| `DISPATCHING` | 禁止重试，只读对账 |
| `UNKNOWN` | 禁止重试，只读对账 |
| `FAILED` | 不自动重放，由用户发起新操作 |
| `MANUAL_REQUIRED` | 告警并人工处理 |

## 5.5 补偿与对账

保留现有 PostgreSQL 审计方向，并增加独立 Worker：

- `FOR UPDATE SKIP LOCKED` 领取 reconcile job。
- 心跳、超时重新认领。
- 指数退避和最大重试。
- 超限进入 `MANUAL_REQUIRED`。
- 对账 Worker 不重新调用原始写接口，只查询 ERP 结果。
- operation 状态积压和最老任务年龄触发告警。

### 验收条件

- 同一 thread 的请求与 resume 不能并发。
- 进程在 ERP 成功后、终态审计前崩溃，不会重复写 ERP。
- `DISPATCHING/UNKNOWN` 只能进入对账。
- 失去 session lease 的执行者无法覆盖新状态。
- 并发消息不会丢失。

---

# 阶段 6：正式切换共享 Agent

只有前五阶段通过后，才删除 per-user Agent。

## 修改 AgentLoader

删除：

- `_sessions`
- `_session_build_locks`
- `_build_agent_for_user()`
- `AgentSession`
- 用户级 `run_lock`

改成：

```text
AgentLoader
├── shared_agent
├── shared_checkpointer
├── shared_store
├── repositories
└── context_loader
```

## 修改 create_main_agent

- 删除 `user_context` 参数。
- System Prompt 只保留静态规则和动态插槽。
- Backend 改为 `RuntimeSandboxBackend`。
- Store namespace 运行时解析。
- 中间件不绑定用户。
- 子 Agent不绑定用户。
- Agent Graph在进程启动时创建一次。

## 单进程验证

先验证：

- 2 个租户
- 每个租户 2 个用户
- 每个用户多个 thread
- 查询、写入、HITL、resume
- 沙箱重建
- 记忆更新
- ERP 对账

### 验收条件

- 同一进程内共享一个 Agent Graph。
- 多用户、多会话能够并发。
- 没有用户级 Agent 缓存。
- 没有用户级运行锁。
- 用户数据、记忆、沙箱、审计全部正确隔离。

---

# 阶段 7：生产部署与多进程验收

采用渐进验证：

## 第一步：两个 Worker

- 取消 `workers=1` 限制。
- 验证 PostgreSQL session/sandbox lease。
- 验证请求可能落在不同 Worker 时仍能 resume。
- 验证同一 thread 不会被两个 Worker 同时执行。

## 第二步：独立后台 Worker

将以下任务从 Web 进程移出：

- 写操作对账
- 审计补偿
- TTL 清理
- 记忆归档
- 沙箱健康检查和回收

## 第三步：多副本

- 多实例部署
- 优雅停机
- readiness/liveness
- 连接池总量控制
- 数据库 migration 独立执行
- Secret Manager
- 日志脱敏
- 故障注入测试

## 监控指标

至少包括：

- Agent run 数量和耗时
- 同一 thread 租约冲突
- 租约心跳失败
- 沙箱领取/重建失败
- 跨租户访问拒绝
- ERP 写操作状态分布
- reconcile job 堆积
- `DISPATCHING/UNKNOWN` 最老时间
- 审批等待时间
- Checkpoint 恢复失败
- 模型和 MCP 超时

### 验收条件

- 跨 Worker resume 正常。
- Worker 崩溃后租约能够过期并被重新认领。
- Web 实例重启不丢审批和对账任务。
- 优雅停机期间不会产生重复写操作。
- 审计、告警和对账链路完整。

# 调整后的关键原则

1. 先认证和隔离，再共享 Agent。
2. RuntimeContext 是请求级依赖，不进入 Checkpoint。
3. Graph State 只保存需要恢复的工作流状态。
4. ContextVar 是便利工具，不是安全边界和持久化机制。
5. HITL 暂停时释放资源，resume 时重新认证并重新获取租约。
6. Checkpoint 恢复不代表 ERP 写操作可以重新执行。
7. 主 Agent和子 Agent共享可信身份，但工具层仍需重新授权。
8. PostgreSQL先承担租约、状态和补偿协调，暂不额外引入 Redis。
9. 前五阶段完成前，不删除 per-user Agent缓存。
10. 一次 ERP 写操作始终对应一个 `operation_id` 和一次持久化审批。

这版计划保留了原方案的总体方向，但把安全隔离和恢复正确性提前到了共享 Agent切换之前，避免迁移过程中出现短暂但危险的串用户窗口。
