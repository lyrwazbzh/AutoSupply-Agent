# 网关转发与 Agent 加载

MCP 独立进程把领域动作暴露成 Tool，经单例 `httpx` 打 Java ERP；路径、camelCase、复杂 JSON 体在网关内映射。Agent 用 `langchain-mcp-adapters` SSE 拉全量列表（失败返回空列表），与 06 本地袋合并。`mcp_tools_bean` 按分析/订单/计划/寻源拆名字，给子 Agent 裁剪参考。

代码：网关 `src/mcp_server/server_main.py`、`server_config.py`、`http_base.py`，工具组 `tools/suppliers_tools.py`、`parts_tools.py`、`order_tools.py`、`inventory_tools.py`、`manufacturing_tools.py`；Agent 侧 `src/agent/tools/mcp_client.py`、`src/agent/mcp_tools_bean.py`。本地袋见 `06/01`；HITL 见同篇；主 Agent 装配见 `03/01`。

出现 `@mcp.tool()`，就是注册函数名 = 工具名。出现 `load_mcp_tools_sync`，就是带缓存的阻塞拉表。出现 `classify_tools`，就是按用途子集，主 Agent 仍拿全量。

---

## 1. 解决什么问题

Agent 提示词里写死 `/api/boms/{code}` 会与 ERP 契约绑死。网关提供稳定工具名与 docstring；HTTP 细节留在网关。BOM / MRP / 质量等数值由 ERP 接口返回，网关不生成、不猜测。

| 侧 | 职责 |
|----|------|
| FastMCP 网关 | 领域动作 → REST；统一连接池与错误 dict |
| `mcp_client` | SSE 拉全量、缓存、降级为空列表 |
| `mcp_tools_bean` | 名字分组，供子 Agent / 用途袋 |
| 主 Agent | `mcp_tools + custom_tools` |

---

## 2. 架构 / 数据流

```text
.env → server_config（MCP_HOST/PORT、ERP_BASE_URL、超时与池）
        │
        ▼
server_main：FastMCP + 五组 register_*_tools
        │
        ▼
SSE 监听（常见 :9000）
        │
        ▼
@mcp.tool → erp_client.get/post/… → Java ERP
        │
        ▼
dict → json.dumps → 模型

并行：
create_main_agent
  → load_mcp_tools_sync（MultiServerMCPClient → MCP_SSE_URL）
  → 重试指数退避，TTL 300s；失败 → []
  → 与本地 custom_tools 合并
```

工具模板：

```text
def register_xxx_tools(mcp):
  @mcp.tool()
  async def snake_name(...) -> str:
      result = await erp_client.get|post|...(path, params|json_data=…)
      return json.dumps(result, ensure_ascii=False, indent=2)
```

Python 参数 snake_case；ERP 路径与 camelCase 写在各 tools 文件里。`params` 里的 `None` 在 `http_base` 发请求前丢掉。

---

## 3. 核心设计与实现

### 3.1 入口与配置

**`server_main.py`。** 独立进程入口：把仓库根插入 `sys.path`；创建 `FastMCP(name="AutoSupply-MCP")`；依次 `register_supplier_tools` / `parts` / `order` / `inventory` / `manufacturing`；`mcp.run(transport="sse", host=MCP_HOST, port=MCP_PORT)`。本文件不直接打 Java。

**`server_config.py`。** MCP 进程自读仓库根 `.env`（不经过 Agent `env_utils`）。

| 变量 | 缺省 | 用途 |
|------|------|------|
| `ERP_BASE_URL` | `http://localhost:8081` | HTTP 客户端 base_url |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `9000` | SSE 监听 |
| `HTTP_TIMEOUT` | `30` | 请求超时（秒） |
| `HTTP_MAX_CONNECTIONS` | `20` | 连接池上限 |

Agent 侧 `MCP_SSE_URL`（常见 `MCP_SERVER_URL` + `/sse`）须与这里 host/port 对齐。

### 3.2 HTTP 薄封装：`http_base.ERPHttpClient`

五组工具最终都走模块级单例 `erp_client`。

**单例与连接池。** `__new__` 保证全局一个实例；`httpx.AsyncClient` 在 `client` 属性懒创建：`base_url`、超时、`max_connections`、`max_keepalive_connections=10`，默认头 `Content-Type: application/json`。连接池贵、可复用 TCP，故 HTTP 客户端用单例；LLM 按任务另取（温度/Key 不同）。

**五个动词。** `get` / `post` / `put` / `patch` / `delete` 均为 async。`params` 先去 `None` 再交给 httpx。`post`/`put` 的 JSON 体走 `json_data`。

**`_handle_response`。** 先 `response.json()`。200：原样返回业务 JSON。非 200：包 `{code, message: "HTTP Error: …", data: 已解析或原文}`。JSON 解析失败：`message` 带正文前 500 字。本层不抛 HTTP 异常给工具；工具拿到 dict 再 `json.dumps` 成字符串回给模型。

**`close`。** `aclose()`；`server_main` 退出路径未统一调用，需关连接时由调用方显式 `await`。

### 3.3 五组领域工具

共同约定：`register_*_tools(mcp)` 内 `@mcp.tool()`；返回 `str`（美化 JSON）；网关无审批逻辑，高风险写回的 HITL 在 Agent 侧（见 06）。

#### 供应商（5）— `suppliers_tools.py`

| 工具 | 方法 / 路径要点 |
|------|-----------------|
| `supplier_query` | GET `/api/suppliers/search`，按名称关键字 |
| `supplier_page` | GET `/api/suppliers/page`；`credit_rating`→`creditRating` |
| `supplier_get` | GET `/api/suppliers/get/{id}` |
| `supplier_create` | POST `/api/suppliers/create`，body camelCase，空可选字段去掉 |
| `supplier_update_status` | PATCH `/api/suppliers/update-status/{id}`，`status` 走 query |

#### 零件（5）— `parts_tools.py`

| 工具 | 方法 / 路径要点 |
|------|-----------------|
| `part_query` | GET `/api/parts/get/{id}` |
| `part_search` | GET `/api/parts/search`，按名称 |
| `part_by_supplier` | GET `/api/parts/supplier/{supplier_id}` |
| `part_page` | GET `/api/parts/page`，可选名/分类/供应商 |
| `part_create` | POST `/api/parts/create`；写侧目前仅 create |

#### 订单（7）— `order_tools.py`

| 工具 | 方法 / 路径要点 |
|------|-----------------|
| `order_create` / `order_update` | POST/PUT；入参 JSON 字符串 `order_data`，`json.loads` 失败直接 `{code:400}`，不打 ERP |
| `order_page` / `order_get` | GET 分页 / 详情（含明细） |
| `order_search_details` | GET 明细行检索（零件名、时间窗） |
| `order_statistics` | GET 汇总（总数、金额、状态分布） |
| `order_update_status` | PATCH，`status` 0–4 走 query |

订单状态语义：0 待审核 → 1 已审核 → 2 已发货 → 3 已收货 → 4 已完成。建单缺字段时 Agent 侧可先走 `request_order_info`。

#### 库存（6）— `inventory_tools.py`

| 工具 | 方法 / 路径要点 |
|------|-----------------|
| `inventory_warning` / `inventory_check` | GET 预警列表 / 总览统计（非逐件盘点录入） |
| `inventory_page` / `inventory_get` | GET 分页 / 单条 |
| `inventory_inbound` / `inventory_outbound` | POST，参数放 **query**，不是 JSON body |

#### 制造供应链（约 20）— `manufacturing_tools.py`

文件头约定：只做领域动作 → ERP/PLM/MES REST 映射。统一小助手 `_result` 做 `json.dumps`。

| 子域 | 工具 |
|------|------|
| 项目 / BOM | `program_search`、`bom_get`、`bom_compare`、`engineering_change_get` |
| 物料 / AVL | `material_search`、`material_get`、`material_alternatives`、`material_avl` |
| MRP / 齐套 | `mrp_shortage_page`、`material_demand_get`、`kit_rate_get` |
| 寻源 | `quotation_compare`；`rfq_create` / `sourcing_nominate`（JSON 字符串入参，解析失败 code=400） |
| 交付 / ASN | `delivery_schedule_page`、`asn_page`、`delivery_performance_get` |
| 质量 / 风险 | `supplier_quality_get`、`ppap_status_get`、`line_stop_risk_page`、`supply_risk_assess` |

三组存量 ERP（供应商/零件/订单/库存）管主数据与采购出入；制造组管项目 BOM → 物料/AVL → MRP/齐套 → RFQ/定点 → 交付/质量/风险。

### 3.4 Agent 侧加载：`mcp_client`

用 `MultiServerMCPClient`，一路名 `"erp"`，`transport="sse"`，`url=MCP_SSE_URL`，`get_tools()` → `List[BaseTool]`。

| 机制 | 行为 |
|------|------|
| 缓存 | TTL 300s；命中直接返回 |
| 重试 | 最多 3 次，`delay = 1.0 * 2^attempt` |
| 降级 | 仍失败或 0 工具 → `[]`，Agent 可对话，仅无 ERP 工具 |
| `force_refresh` / `invalidate_cache` | 跳过缓存或清空；MCP 重启、工具集变更后用 |

**`load_mcp_tools_sync`。** 供 `create_main_agent`：先看缓存；无 running loop → `asyncio.run`；已在异步上下文 → `ThreadPoolExecutor` 里再 `run`（超时 30s），避免嵌套 loop。

### 3.5 用途拆袋：`mcp_tools_bean`

不连 MCP、不打 ERP。两张子串模式表 + `classify_tools(all_tools)`。

| 出参键 | 匹配方式 | 用途 |
|--------|----------|------|
| `analyst_tools` | `ANALYST_TOOL_PATTERNS` 子串 | 读多写少：供应商/零件/库存读、订单检索统计、BOM/MRP/齐套、本地 `generate_chart`/`web_search` 等 |
| `order_tools` | `ORDER_TOOL_PATTERNS` 子串 | 订单写与交付协同：建改单、HITL `request_order_info`、交付/质量只读等 |
| `planning_tools` | 精确名元组 | 项目/BOM/需求/缺料/齐套/停线风险 |
| `sourcing_tools` | 精确名元组 | 物料检索/AVL/比价/RFQ/定点/PPAP |
| `all_tools` | 原样带回 | 全量 |

与子 Agent YAML `tools:` 白名单同一套名字口径。主 Agent 仍拿全量 MCP + 本地袋；本文件服务「按用途子集」。扩展时：分析/订单袋加稳定子串；计划/寻源袋加精确名，并保证运行时 `all_tools` 已加载同名工具。

```text
mcp_client → List[BaseTool]
        ▼
classify_tools → analyst / order / planning / sourcing
        │
子 Agent YAML tools:（装配白名单）
```

---

## 4. 关键设计取舍

| 取舍 | 现行做法 |
|------|----------|
| 契约稳定 | 模型选动作名；路径与字段映射集中在网关 |
| 连接 | HTTP 客户端单例复用池；LLM 按任务取 |
| 复杂体 | 订单/RFQ/定点用 JSON 字符串参数；解析失败 code=400，不打 ERP |
| 审批 | 网关无审批；HITL 在 Agent（interrupt） |
| 可用性 | MCP 挂了返回空列表，本地袋仍可用 |
| 数值 | BOM/MRP/质量等只转发 ERP 结果 |

---

## 5. 工程边界

| 主题 | 现行行为 |
|------|----------|
| 进程拆分 | MCP 与 FastAPI/Agent 常为两进程；`.env` 网关自加载 |
| 传输 | 现行 `transport="sse"`；URL 以 `/sse` 结尾 |
| 缓存 | 默认 5 分钟；ERP 新增工具需等 TTL，或 `force_refresh` / `invalidate_cache` |
| 非 200 | 仍返回 dict，工具侧 dumps 给模型，由模型/上层解读 |
| bean 与加载 | 未加载到的精确名自然缺席；子串组只收录当前 `all_tools` 能匹配到的 |
| 写操作参数形态 | 出入库走 query；订单/RFQ 复杂体走 JSON 字符串 |

---

## 6. 面试记忆点

**为什么不让 Agent 直接 httpx？**  
工具 schema、路径与字段映射集中在网关；模型只选动作名与参数。

**SSE 怎么对齐？**  
网关 `mcp.run(transport="sse")`；Agent `MCP_SSE_URL` 指向同一 host/port 的 `/sse`。

**主 Agent 和子 Agent 工具差在哪？**  
主 Agent：全量 MCP + 本地袋。子 Agent：YAML 白名单 / bean 分组裁剪。

**连不上 MCP 会怎样？**  
`load_mcp_tools*` 返回 `[]`；对话与本地工具仍可用。

**收束。** 网关是 ERP 的工具门面；`mcp_client` 是 Agent 的远程工具来源；与 06 本地袋合并才是完整工具面。复习时先对节 2 总流，再对 3.2 模板与 3.3 域表，最后 3.4 / 3.5。
