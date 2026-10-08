# 图表、文档、HITL 与联网

主 Agent 的 `custom_tools` 是宿主机上的 LangChain `@tool`，与 MCP 拉来的 ERP 工具拼成完整工具面。图表强制沙箱出图；文档优先沙箱、可回退本机；产物经 `download_sandbox_file` 落到 `src/download` 供 HTTP 取；缺订单字段时 `request_order_info` 走 LangGraph `interrupt`；联网与技能安装走 DeepSeek / `web_fetch` / `install_skill`。

代码：`src/agent/tools/chart_generator.py`、`document_generator.py`、`download_sandbox_file.py`、`hitl_tools.py`、`web_search.py`、`web_fetch.py`、`skill_management.py`、`memory_tools.py`、`mcp_client.py`；装配 `src/agent/main_agent.py`；HITL SSE 见 `src/api_view/api/chat.py`。沙箱句柄见 `08/01`；技能包与 Sync/Restore 见 `09/01`；记忆见 `07/01`；MCP 网关见 `05`。

出现 `custom_tools`，就是与 MCP list 拼接前的本地袋。出现 `interrupt`，就是图停在 `state.next` 非空等 resume。出现 `/workspace/charts` / `/workspace/output`，就是沙箱内产物目录。

---

## 1. 解决什么问题

ERP / MCP 给业务读写；还要出 PNG 与报告、把容器文件交到浏览器、缺字段时停下来问人、临时搜网或装技能。这些放进 MCP 网关既重又难隔离，故落在宿主 `@tool` + 沙箱执行面。

| 能力面 | 代表工具 | 执行落点 |
|--------|----------|----------|
| 可视化 | `generate_chart` | 沙箱 matplotlib → `/workspace/charts/` |
| 文稿导出 | `generate_document` / `generate_table_report` | 优先 `/workspace/output/`，可回退 `src/download/` |
| 产物出站 | `download_sandbox_file` / `list_sandbox_files` | Docker 抽到宿主机 → `/api/download/...` |
| 人机补齐 | `request_order_info` | LangGraph `interrupt` ↔ SSE resume |
| 联网 | `web_search` / `web_fetch` | 宿主 HTTP（DeepSeek 搜 / 直拉页面） |
| 自定义技能 | `install_skill` / `list_user_skills` | 沙箱校验 + 三处落点；细节见 09 |
| 跨会话记忆 | `read_memory` / `remember`（配置开时） | Store + MemoryKeeper；细节见 07 |
| ERP 远程 | `load_mcp_tools_sync` 拉入 | MCP SSE 网关；非本地袋本体 |

子 Agent YAML 可点名其中若干（如 `generate_chart`），由 loader 匹配进子工具袋。

---

## 2. 架构 / 数据流

### 2.1 装配

```text
create_main_agent
  mcp_tools = load_mcp_tools_sync()          # 远程 ERP
  custom_tools = [
    generate_chart,
    generate_document, generate_table_report,
    download_sandbox_file, list_sandbox_files,
    request_order_info,
    web_search, web_fetch, install_skill, list_user_skills,
    (+ read_memory, remember 若 MEMORY_TOOLS_ENABLED)
  ]
  all_tools = mcp_tools + custom_tools
```

多数沙箱相关工具经 `sandbox_holder.get_sandbox()` 取当前请求绑定的 Proxy。下载工具另用 Docker SDK 按容器名查找（见节 5）。

### 2.2 产物链路

```text
generate_chart / generate_document
        │  写入沙箱
        │  /workspace/charts | /workspace/output
        ▼
download_sandbox_file(remote_path)
        │  Docker base64 → src/download/
        ▼
GET /api/download/<name>   （web_main 与 DOWNLOAD_DIR 同一目录）
```

差异：图表无沙箱则返回错误字符串，不在宿主机画图；文档写沙箱失败或无沙箱时可写本地并直接给下载 URL。

### 2.3 HITL 链路

```text
模型调用 request_order_info
  → interrupt({ type: order_info_request, missing_fields, current_data, … })
  → chat SSE event interrupt / order_info_supplement
  → 前端表单 → Command(resume=supplement)
  → parse_supplement_text + validate_order_data
  → 齐则返回订单 JSON；否则再 interrupt（最多 5 轮）
```

与 MCP `order_create`：网关转发完整体；缺字段停顿与补齐在 Agent 侧 HITL。审批类 interrupt（`action_requests`）另走 `hitl_approval` SSE，由写操作工具上的 interrupt 配置触发。

---

## 3. 核心设计与实现

### 3.1 图表：`generate_chart`

单一 `@tool` 收纳多种类型（`CHART_TYPES`：柱/线/饼/散点/热力/雷达/瀑布/桑基等，共 26 种）。图必须在沙箱 `/workspace/charts/` 生成；用户要落到本机时走 `download_sandbox_file`。

**入口。** `chart_type` 必须在枚举内。`data` 为非空 JSON list；解析失败返回错误文案。`get_sandbox()` 为空 →「请确保 Docker 沙箱已启动」。

**沙箱内流程。** 按标题与时间戳拼 PNG 名 → `write_file` 写 params JSON 与内嵌 `CHART_SCRIPT`（matplotlib Agg、中文字体回退、按类型绑图）→ `pip install matplotlib numpy`（失败可忽略，靠镜像缓存）→ `python script params`（超时 30s）→ 删临时 params/script。

**成功条件。** `exit_code == 0` 且 stdout 含 `OK:`，且 `file_exists(output_path)`。返回标题、类型、点数、大小、沙箱路径，并提示下载工具。字段约定：默认 `x_field=label`、`y_field=value`；分组/多线用 `series_field`；散点等可用 `x`/`y`。更细字段见 `src/skills/procurement/chart_params.md`。

### 3.2 文档：`generate_document` / `generate_table_report`

把分析结论、对比表、导出数据写成可下载文件。优先 `/workspace/output/`；失败或无沙箱回退仓库 `src/download/`，并给 `http://localhost:8000/api/download/...`。

**`generate_document`。** `title`、`content`、`format`（markdown / html / csv / json / text）、可选 `filename`。按 format：Markdown 加标题与时间；HTML 完整页；CSV 若 content 是对象数组 JSON 则按表头写出；JSON 包 `title` / `generated_at` / `data`；纯文本加抬头。最终进 `_write_to_sandbox_or_local`。

**`generate_table_report`。** `headers`、`rows` 均为 JSON 字符串；拼 Markdown / HTML 表，或转对象列表再走 CSV；内部 `generate_document.invoke(...)` 复用落盘。供应商清单、零件表、订单明细等结构化结果优先走此工具。

### 3.3 下载桥：`download_sandbox_file` / `list_sandbox_files`

对接图表与文档产物，也支持其它沙箱绝对路径。与 `web_main` 下载路由同一 `src/download`。

**`download_sandbox_file`。** `remote_path` + 可选 `filename`（默认 basename）。

1. 主路径：Docker SDK 找运行中的 `erp-sandbox` / `erp-sandbox-default_user`，或任意 `erp-sandbox-*` → `test -f` → `stat` → 容器内 `base64` 读出（兼文本与 PNG）→ 宿主机 `write_bytes` → 返回下载 URL 与本地路径  
2. 回退：Docker 不可用且 `remote_path` 在宿主机上已是文件 → 拷贝到 download  

两边都失败则汇总说明。

**`list_sandbox_files`。** 默认列 `/workspace`，`ls -lah`；沙箱不可用则直接说明。便于下载前确认路径。

### 3.4 HITL：`request_order_info`

模型发现建单/改单数据不齐时调用；内部 `interrupt` 挂起当前图，等前端把补充送回来再合并校验。

**必填。** 头：`orderNumber`、`orderDetail`（至少一条）。明细：`partId`、`quantity`、`unitPrice`。`validate_order_data` 返回缺失名（明细写成 `orderDetail[i].xxx`）。

**`parse_supplement_text`。** 能当 JSON dict → `update`；否则正则从自由文本抽零件/物料 ID、数量、单价（中英关键词），写入 `orderDetail[0]`。

**循环。** 入参 `extracted_data`、`missing_fields`（JSON 字符串）。最多 5 轮：已齐返回完整订单 JSON；否则 `interrupt({ type: "order_info_request", … })`。chat 层将该 type 打成 SSE `order_info_supplement`；resume 取 `supplement`（或纯字符串）→ parse + validate。5 轮仍缺则返回带 `error` 与 `current_data` 的 JSON。

`interrupt` 与普通工具失败：前者图停在可 resume 状态；后者是 ToolMessage 错误文本，图继续。

### 3.5 联网：`web_search` / `web_fetch`

**`web_search(query)`。** DeepSeek Responses API 内置 `web_search`：宿主只发 HTTP、收中文摘要。共用 `DEEPSEEK_API_KEY`；`model` 用 `WEB_SEARCH_MODEL`（默认 `deepseek-flash`），与可能不同的聊天 `LLM_MODEL` 分开。`tool_choice` 强制 `web_search`。超时 30s。解析优先顶层 `output_text`，否则扫 `output` 里 message 文本。

**`web_fetch(url, max_chars=8000)`。** 协议须 http/https；`httpx.get`（跟重定向、超时 20s）。HTML `_strip_html`；其它类型用原文；超长截断并注明总长。

分工：搜索给摘要；`web_fetch` 给指定页正文（文档、Skill 源、在线说明）。

### 3.6 技能相关本地工具（摘要）

| 工具 | 职责 |
|------|------|
| `install_skill` | URL 下载 → 沙箱临时目录校验 → 宿主 `src/skills/<name>/` + `/skills/custom/` + 用户 Store；可选沙箱 pip |
| `list_user_skills` | 只读 Store，按 key 前缀聚合自定义技能名与文件数 |

校验细则、Sync/Restore、bootstrap 见 **09**。仓库内另有 `assign_skill` 模块（按 scope 复制技能目录）；主 Agent 当前 `custom_tools` 列表未挂入该工具，scope 分配以 09 与技能手册为准。

联网与自定义技能闭环：`web_search` 搜 → `web_fetch` 打开页 → `install_skill` 装包 → `list_user_skills` 查已装。

### 3.7 记忆工具（摘要）

`MEMORY_TOOLS_ENABLED`（默认开）时挂入 `read_memory` / `remember`。COLD 不进 system；跨会话指代与「记住…」走这两工具，底层 `MemoryKeeper`。分层与中间件见 **07**。

### 3.8 MCP 加载：与本地袋拼面

`mcp_client.py` 用 `langchain-mcp-adapters` 经 SSE 连网关（`MCP_SSE_URL`），`get_tools()` 得到远程 `BaseTool` 列表。进程内缓存 TTL 300s；失败指数退避最多 3 次；仍失败返回 `[]`（Agent 可对话，仅无 ERP 工具）。`load_mcp_tools_sync` 供 `main_agent` 同步装配：无 running loop 用 `asyncio.run`，已在异步上下文则丢线程池再 `run`（超时 30s）。`invalidate_cache` 在 MCP 重启或工具集变更后可调。

与 `mcp_tools_bean`：本文件拉全量；bean 按分析/订单等用途拆名字给子 Agent。远程 ERP + 本地袋 = 主 Agent 完整工具面。网关转发细节见 **05**。

```text
server_main（SSE）
        ▲ MultiServerMCPClient.get_tools()
mcp_client.load_mcp_tools[_sync]
        ▼
create_main_agent：mcp_tools + custom_tools
```

---

## 4. 关键设计取舍

| 取舍 | 现行做法 |
|------|----------|
| 画图隔离 | 脚本与入口分居容器/宿主机；无沙箱不降级本机画图 |
| 文档可用性 | 优先沙箱；失败回退本地并直接给 URL，保证无 Docker 时仍能出稿 |
| 订单缺参 | 写操作 MCP 仍可叠 HITL；补齐循环在 Agent，网关只收完整体 |
| 搜索密钥 | 复用 DeepSeek Key + 内置 web_search，不另配 Tavily |
| 技能安装 | 沙箱先校验再三落点；危险模式 warning，路径穿越/超大文件失败（见 09） |

---

## 5. 工程边界

| 主题 | 现行行为 |
|------|----------|
| 沙箱句柄 | 图表/文档写路径用 `get_sandbox()`（请求级 Proxy）。`download_sandbox_file` 用 Docker SDK 按 `erp-sandbox-*` 名查找，与 Proxy 映射可能不是同一条路径，多用户/热替换场景以下载工具实际连到的容器为准 |
| 无沙箱时 | chart / list_sandbox 返回错误字符串，模型应改口说明；document 可本地落盘 |
| `generate_table_report` | 依赖 `generate_document` 已注册（同文件 invoke） |
| 图表约定 | 种类与字段见工具 schema 与 `chart_params.md` |
| 记忆开关 | `memory_tools_enabled=False` 时袋中无 `read_memory`/`remember` |
| MCP 失败 | 空列表不挡建图；本地袋仍可用 |

---

## 6. 面试记忆点

**26 种图在哪执行？**  
容器里跑 `CHART_SCRIPT`；类型枚举在 `CHART_TYPES` / 工具 schema / skill 文档。

**interrupt 和普通工具失败？**  
interrupt：图停在可 resume。工具失败：ToolMessage 错误文本，图继续。

**图表和文档对沙箱的态度差在哪？**  
图表强制沙箱；文档优先沙箱、可回退本地并给下载链。

**本地袋和 MCP 怎么拼？**  
`all_tools = load_mcp_tools_sync() + custom_tools`；ERP 远程，呈现/HITL/联网/记忆在本地。

**收束。** 本地袋补齐「算完之后怎么呈现、怎么问人、怎么联网」；执行隔离见 08，技能包见 09，记忆见 07，MCP 见 05。复习时先对节 2 三条链路，再对 3.1～3.4。
