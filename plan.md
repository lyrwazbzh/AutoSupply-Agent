# Smart-Car 能力补充计划

> 状态：方案已定，**实现未开始**（先读源码 / 对齐本计划再动手）。  
> 底座：本仓 Smart-Car（Harness 四阶段、三层记忆、制造 MCP、Docker 沙箱、Next HITL）。  
> 参考实现：`ERP_OPENCLAW`（仓内 Java ERP、`asu_finance`、`asu_eval`）。  
> 原则：Smart-Car 当底座；从 OPENCLAW **搬模块、改接线**，不做两仓硬 merge。

---

## 1. 要补的三块

| 模块 | 做成什么样算完成 | 明确不做 / 边界 |
|------|------------------|-----------------|
| **仓内 ERP** | 本仓可起 Java ERP；供应商 / 零件 / 订单 / 库存等 MCP **真读写**；HITL 审批后能落库 | 不把 BOM/MRP 等制造接口全用 Java 重写 |
| **制造 Mock 层** | Smart-Car 制造 21 工具（`/api/programs`、`/api/boms`、`/api/mrp`…）有可演示合成数据 | 不假装「Java ERP 已支持制造全量 API」 |
| **asu_finance** | EvidenceStore + API router + `create_finance_tools` 挂进 Agent；财报导入、FTS5 回查、Decimal 计算可演示 | 不上真实征信 / 银行；不做向量 RAG |
| **asu_eval** | Store + capture/enqueue + Worker + gate；在 `chat.py` SSE **终态旁路采集** | 不吹「模型准确率」；只做工程门禁与回归 |

说明：财务 / 评估与采购 Agent **相对独立**，可分 PR 接入，不依赖制造 Mock 全部完成。

---

## 2. 前置结论（读源码时重点核对）

### 2.1 ERP 路径：基础采购对得上，制造对不上

- OPENCLAW `erp-service` 已有路径（`/api/suppliers|parts|orders|inventory|customers|logistics|statistics/...`）与 Smart-Car **经典采购类 MCP** 路径基本一致 → 可直接配 `ERP_BASE_URL` 指向仓内 Java。
- Smart-Car **制造 21 工具** 使用的 `/api/programs`、`/api/boms`、`/api/mrp`、`/api/rfqs`、`/api/asns`、`/api/risks`… 在 Java ERP **不存在** → **必须加 Mock 制造层**（Python FastAPI 或 MCP 内分支），与 Java 并存。

核对锚点（本仓）：

- MCP 透传：`src/mcp_server/http_base.py`、`server_config.py`（`ERP_BASE_URL`）
- 制造工具：`src/mcp_server/tools/manufacturing_tools.py`
- 采购工具：`suppliers_tools.py` / `parts_tools.py` / `order_tools.py` / `inventory_tools.py`

参考锚点（OPENCLAW）：

- Java 路由清单：`erp-service/src/test/resources/endpoint-manifest.json`
- 控制器：`SuppliersController` / `PartsController` / `OrdersController` / `InventoryController` 等

### 2.2 财务：EvidenceStore + Router + Agent 工具

- `asu_finance`：EvidenceStore、API（`create_finance_router`）、`create_finance_tools` 注册进 Agent。
- OPENCLAW 挂载示例：`api_view/web_main.py` → `include_router(..., prefix="/api")`；主 Agent 引入财务工具。

### 2.3 评估：旁路采集，不堵主响应

- `asu_eval`：Store + `capture_completed_run` / `enqueue_completed_run` + Worker + `gate`。
- OPENCLAW 多经 lab/observability；**本仓应对齐到 `src/api_view/api/chat.py` 的 SSE 终态**（含 HITL resume 完成后的结束路径）。

---

## 3. 目标架构（集成后）

```
Next.js ──SSE──▶ Smart-Car FastAPI
                    ├─ DeepAgent（Harness + 记忆 + HITL）     ← 保留
                    ├─ MCP ──▶ erp-service（Java，仓内）        ← 新增
                    │            └─ manufacturing Mock         ← 新增（制造 21）
                    ├─ /api/* finance（asu_finance）          ← 新增
                    ├─ create_finance_tools → Agent           ← 新增
                    └─ enqueue ──▶ asu_eval Worker              ← 新增
```

分流约定（建议）：

- 采购类 path → Java `:8081`
- 制造类 path → Mock（独立端口或同网关按前缀转发）
- 由 `ERP_BASE_URL` + `MFG_MOCK_BASE_URL`（或 MCP 内 `ERP_MODE`）配置，禁止写死混用后无法排查

---

## 4. 分阶段落地（严格按序）

### Phase A — 仓内 ERP + 制造 Mock

1. 将 OPENCLAW `erp-service/` 纳入本仓（可放仓库根目录 `erp-service/`）。
2. `.env` / `.env.example`：`ERP_BASE_URL=http://localhost:8081`；对齐 Java 侧 API Key（若有 Filter）。
3. 启动说明：先起 ERP，再起 MCP / API / 前端。
4. 验收黄金路径：**库存或供应商查询 → `order_create` HITL → 批准 → ERP 库有单**。
5. 新增制造 Mock：覆盖 `manufacturing_tools.py` 所用 REST；合成 NEV 场景数据即可。
6. 文档：工具账写清「基础域 = 仓内 Java；制造域 = Mock」，禁止夸大。

**Exit：** 不依赖外部黑盒 8081，也能演示「查询 + 审批落库」；制造工具不再空链。

### Phase B — `asu_finance`

1. 拷贝 / 迁入 `src/asu_finance/`（含 EvidenceStore 与本地数据目录约定，数据目录 gitignore）。
2. `web_main.py`：`include_router(create_finance_router(...), prefix="/api")`。
3. 认证：一期可用固定 demo `user_id` 薄封装，再视需要接正式登录。
4. `main_agent`：注册 `create_finance_tools`；财务研究 / 复核工具权限与提示词边界对齐（可参考 OPENCLAW 子 Agent 限制）。
5. 前端：一期可用 API 验收；Next「证据工作台」可二期。

**Exit：** 导入合成财报 → 检索带行号/页码引用 → Decimal 指标可算；Agent 能调财务工具。

### Phase C — `asu_eval`

1. 迁入 `src/asu_eval/` + `evals/`（可先缩到采购相关 5～12 条黄金例）。
2. `chat.py`：run 完成（含 resume 终态）调用 `enqueue_completed_run`。
3. 独立进程：`python -m asu_eval.worker`；队列 / DB 路径本地化并 gitignore。
4. 门禁脚本：`asu_eval.gate`；与 Phase A 路径（期望工具序、是否 interrupt）对齐。
5. 「评估中心」UI 二期；一期 CLI + API 足够。

**Exit：** 一次完整采购会话可入队、可打分、门禁脚本可跑。

---

## 5. 目录与改动面（预估）

| 动作 | 路径 |
|------|------|
| 新增 | `erp-service/` |
| 新增 | `src/asu_finance/`、`src/asu_eval/`、`evals/` |
| 新增 | `src/mcp_server/mock_manufacturing/` 或根目录 `mock_erp_mfg/` |
| 改 | `src/mcp_server/server_config.py`、`.env.example` |
| 改 | `src/api_view/web_main.py`、`src/api_view/api/chat.py` |
| 改 | `src/agent/main_agent.py`（挂财务工具） |
| 改 | README / 启动脚本（可选 `start_all.py`） |
| 本文档 | `plan.md`（本文件）随实现更新状态 |

**尽量不改（读源码时当作稳定核心）：**

- `src/agent/harness.py` / `harness_config.yaml`
- 三层记忆（`memory/keeper.py`、Warm/Cold 中间件）
- 现有中间件栈顺序（只追加工具与路由，不重排 Harness）

---

## 6. 风险与对策

| 风险 | 对策 |
|------|------|
| 制造 API 在 Java 不存在 | Phase A **强制** Mock；文档与 Demo 话术分离「Java vs Mock」 |
| 财务 / 评估依赖 OPENCLAW auth | 一期 demo user；不阻塞主链路 |
| 双前端（Vue 参考 vs 本仓 Next） | 财务 / 评估先 API；UI 后补 |
| 范围膨胀 | 三阶段各自有 Exit；不做一次搬完整个 `asu_lab` |
| MCP 失败仍静默空工具 | 联通 ERP 时顺手统一失败语义（超时 / 连接失败结构化返回）——可作为 A 的附属小项 |

---

## 7. 工作量直觉

| 阶段 | 预估 | 对外一句话 |
|------|------|------------|
| A 仓内 ERP + 制造 Mock | 约 4～7 天 | 仓内可审批落库；制造可演示 |
| B 财务 | 约 3～5 天 | 证据可回查 + Agent 可算 |
| C 评估 | 约 4～6 天 | 旁路评估 + 黄金门禁 |

合计大约 **2～3 周**（视读源码与联调情况浮动）。

---

## 8. 建议的第一个 PR（最小）

只做 Phase A 的前半：

1. 纳入 `erp-service`
2. 配置 `ERP_BASE_URL`（及 API Key）
3. 启动说明 + 一条手工验收（下单审批落库）

制造 Mock、`asu_finance`、`asu_eval` 分后续 PR。  
**动手前：** 把本仓 MCP 路径与 `endpoint-manifest.json` 再对一遍清单，标出「直接可用 / 需改 path / 走 Mock」。

---

## 9. 读源码检查清单（给你自己用）

在开始编码前建议读完并在下表打勾：

- [ ] `main_agent.py`：工具组装、`interrupt_on`、中间件顺序
- [ ] `harness.py` + `harness_config.yaml`：阶段与 Review 策略
- [ ] `memory/`：HOT/WARM/COLD 与 Keeper 写入口
- [ ] `mcp_server/`：全部 tools 与 `http_base` 错误处理
- [ ] `api_view/api/chat.py`：SSE 事件类型、interrupt / resume、**何处算 run 结束**
- [ ] 前端 HITL：`ApprovalCard` / resume 决策
- [ ] OPENCLAW：`erp-service` 启动与 seed；`asu_finance` / `asu_eval` 最小调用链

---

## 10. 状态记录

| 日期 | 状态 |
|------|------|
| 2026-09-27 | 方案写入本文件；实现未开始；等待源码阅读完成后再开 Phase A |

变更本计划时：改对应章节，并在本节追加一行状态，避免口头方案与文档漂移。
