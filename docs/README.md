# Smart-Car docs 总览与维护指南

> 本目录是 Smart-Car（新能源汽车整车制造采购与供应链助手）的**后端设计 + Agent 岗面试学习资料**，按能力域分文件夹组织。  
> 产品闭环：HTTP/SSE 入口 → 会话 Agent 装配 → Harness 阶段与评审 → 子 Agent 委派 / MCP 查 ERP / 本地工具与沙箱 → 记忆与 Skills。  
> **先读这里**：知道整体结构、每篇讲什么、以及「新增功能时文档放哪」。

主链心智：

```text
FastAPI 入口 → 会话 Agent → Harness 阶段
  → 工具（MCP / 本地）与子 Agent 委派
  → 沙箱执行 / 记忆 / Skills
  → SSE 回前端
```

旧平铺文档（`api.md`、`harness.md`、`tool.md`、`mcp_server.md`、`subagents.md`）已按域重写进下列文件夹，不再一对一保留原文件名。

---

## 一、目录结构与索引

```text
docs/
├── README.md                              ← 本文件
├── 00-总览与面试开场/
├── 01-入口与运行时/                       FastAPI、lifespan、SSE、会话历史
├── 02-会话持久化与Store/                  AgentLoader、Mongo Store / Checkpointer
├── 03-Agent核心与Harness/                 create_main_agent、阶段、rubric
├── 04-子Agent与委派/                      YAML 规格、task 门禁、派发事件
├── 05-MCP与ERP桥/                         FastMCP 网关 + Agent 侧加载
├── 06-本地工具袋/                         chart / 文档 / HITL / 联网 / 记忆工具
├── 07-三层记忆/                           HOT / WARM / COLD、Keeper、抽取
├── 08-沙箱隔离/                           五态池、Proxy、健康与熔断
├── 09-Skills/                             SKILL.md、安装、同步到沙箱
└── 99-面试速记/
```

| 状态 | 路径 | 一句话 | 写前必读源码 |
|------|------|--------|--------------|
| 已写 | `00-总览与面试开场/01-能力地图与主链.md` | 产品能力 ↔ 源码主链 | 根 `README.md`、本文件 |
| 已写 | `01-入口与运行时/01-FastAPI入口与生命周期.md` | uvicorn、CORS、下载、沙箱维护循环 | `web_main.py`、`web_config.py` |
| 已写 | `01-入口与运行时/02-SSE对话与会话历史.md` | chat SSE、resume、history CRUD | `api/chat.py`、`api/history.py`、`schema.py` |
| 已写 | `02-会话持久化与Store/01-AgentLoader与Mongo.md` | 按用户建 Agent、checkpoint、Store | `agent_loader.py`、`mongodb_store.py` |
| 已写 | `03-Agent核心与Harness/01-主Agent装配.md` | LLM、工具袋、中间件栈、bootstrap | `main_agent.py`、`config.py`、`middleware_config.py` |
| 已写 | `03-Agent核心与Harness/02-Harness阶段与评审.md` | phase / rubric / grader | `harness.py`、`harness_review.py`、`harness_config.yaml` |
| 已写 | `04-子Agent与委派/01-加载规格与委派门禁.md` | 四角色 YAML、task 校验、回流 | `loader.py`、`task_dispatch.py`、`dispatch_events.py`、四份 yaml、`delegation_gate.py`、`memory/AGENTS.md` |
| 已写 | `05-MCP与ERP桥/01-网关转发与Agent加载.md` | FastMCP → Java ERP；SSE 拉工具 | `server_main.py`、`server_config.py`、`http_base.py`、五组 tools、`mcp_client.py`、`mcp_tools_bean.py` |
| 已写 | `06-本地工具袋/01-图表文档HITL联网.md` | custom_tools 全表 | 见第三节 06 行 |
| 已写 | `07-三层记忆/01-Keeper与注入.md` | 命名空间、评分、中间件 | 见第三节 07 行 |
| 已写 | `08-沙箱隔离/01-五态池与健康.md` | Manager / Proxy / 健康 / 熔断 | 五态 py、`seccomp.json`、健康与熔断中间件 |
| 已写 | `09-Skills/01-目录安装与同步.md` | 采购技能包、install、同步 | 见第三节 09 行 |
| 已写 | `99-面试速记/高频问答速查.md` | 跨模块抽题 | 各域成篇 |

建议阅读顺序：`00/01` → `01/01` → `01/02` → `02/01` → `03/01` → `03/02` → `04` → `05` → `06` → `07` → `08` → `09`。

---

## 二、能力域划分

| 域 | 装什么 |
|----|--------|
| 00 总览 | 项目级介绍、能力地图（非单文件实现） |
| 01 入口与运行时 | FastAPI app、lifespan、SSE、history HTTP |
| 02 会话持久化 | 按用户 Session、Mongo Store / Checkpointer、展示消息 |
| 03 Agent 核心 | `create_main_agent`、Harness 阶段与评审、中间件装配 |
| 04 子 Agent 与委派 | YAML 加载、`task` 门禁、派发观测 |
| 05 MCP 与 ERP | FastMCP 进程、五组工具、Agent 侧 SSE 加载 |
| 06 本地工具袋 | `custom_tools` 各实现 |
| 07 三层记忆 | Keeper、embedding、抽取、WARM/COLD 中间件 |
| 08 沙箱隔离 | Docker 五态、Proxy、健康检查、熔断 |
| 09 Skills | `src/skills` 包、安装工具、同步进容器 |
| 99 面试速记 | 跨模块速查 |

判定：HTTP/SSE → 01；落库与按用户缓存 Agent → 02；图怎么组装、阶段怎么写 → 03；`task` 子 Agent → 04；ERP 工具名 → 05；`@tool` 本地函数 → 06；Store 记忆 → 07；容器 → 08；SKILL.md → 09。

---

## 三、源码覆盖（`src/`，不含 `src/test/`）

| 域 | 文件 |
|----|------|
| 01 | `api_view/web_main.py`、`web_config.py`、`api/chat.py`、`api/history.py` |
| 02 | `api_view/agent_loader.py`、`mongodb_store.py`；`agent/schema.py`（ChatRequest / ResumeRequest / ProcurementContext） |
| 03 | `main_agent.py`、`config.py`、`env_utils.py`、`log_utils.py`、`runtime_context.py`、`middleware_config.py`、`schema.py`（Phase / Plan / ReviewResult）、`harness.py`、`harness_review.py`、`harness_config.yaml`、`middlewares/context_injection.py`、`middlewares/tools_summarization.py` |
| 04 | `subagents/loader.py`、`task_dispatch.py`、`dispatch_events.py`、`configs/procurement_analyst.yaml`、`configs/strategic_sourcing.yaml`、`configs/procurement_order.yaml`、`configs/supplier_quality_risk.yaml`、`middlewares/delegation_gate.py`、`memory/AGENTS.md` |
| 05 | `mcp_server/server_main.py`、`server_config.py`、`http_base.py`、`tools/suppliers_tools.py`、`tools/parts_tools.py`、`tools/order_tools.py`、`tools/inventory_tools.py`、`tools/manufacturing_tools.py`、`agent/tools/mcp_client.py`、`mcp_tools_bean.py` |
| 06 | `tools/chart_generator.py`、`document_generator.py`、`download_sandbox_file.py`、`hitl_tools.py`、`web_search.py`、`web_fetch.py`、`skill_management.py`、`assign_skill.py`、`memory_tools.py`；`mcp_client.py` 加载侧见 05 |
| 07 | `memory/__init__.py`、`keeper.py`、`config.py`、`types.py`、`namespaces.py`、`scoring.py`、`rewrite.py`、`embeddings.py`、`extractor.py`、`run_config.py`、`prompts.py`、`AGENTS.md`；`middlewares/warm_memory.py`、`memory_update.py`、`memory_consolidation.py` |
| 08 | `backends/sandbox_manager.py`、`sandbox_holder.py`、`sandbox_setup.py`、`sandbox_proxy.py`、`custom_opensandbox.py`、`seccomp.json`；`middlewares/sandbox_health.py`、`sandbox_breaker.py` |
| 09 | `skills/pdf-image-text-extractor.md`、`skills/procurement/chart_params.md`、`skills/main/skill-management/SKILL.md`、`download_skill.py`、`skills/procurement/web-scraper/SKILL.md`、`scraper.py`、`web-content-fetcher/SKILL.md`、`fetcher.py`、`procurement-analysis/SKILL.md`、`price-comparison/SKILL.md`、`inventory-optimizer/SKILL.md`、`supplier-analysis/SKILL.md`、`supplier-price-urls/SKILL.md`、`report-generator/SKILL.md`；`tools/assign_skill.py`、`skill_management.py`、`web_fetch.py`（`install_skill`）；`middlewares/skills_sync.py`、`user_skills_restore.py` |

`src/test/` 只在各篇 §5/§6 按需引用，本目录不单独成篇。

---

## 四、单篇模板

与 Data Agent 学习资料同一骨架：`§1 问题` → `§2 数据流` → `§3 实现` → `§4 取舍` → `§5 踩坑` → `§6 问答` → `§7 概念` → 收束。流程图按内容选用。正文只陈述现行条件与步骤。

---

## 五、约定

- 本目录是面试学习主线；前端 `frontend/` 不占主线篇目。  
- 新增功能：先判断域，再在该文件夹加 `NN-功能名.md`，并改本文件索引表。  
- 源码变更后同步对应篇 §3 / §4。
