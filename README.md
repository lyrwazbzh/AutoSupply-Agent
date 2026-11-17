# AutoSupply-Agent

面向汽车与摩托车零部件采购的全栈智能采购平台。项目聚焦供应商、零部件、报价、采购订单、
收货入库、库存流水、补货和采购退货，不涉及整车采购、整车销售或整车生产。

系统由两部分共同组成：

- 以 DeepAgents、LangGraph 和 FastMCP 为核心的采购 Agent，负责自然语言交互、任务规划、
  数据分析、受控写操作、人工审批和结果审查。
- 以 Spring Boot、MySQL 和 Redis 为核心的 Java ERP，负责身份权限、采购业务、库存事务、
  幂等写入和业务审计。

Next.js 前端同时提供对话式智能助手和结构化 ERP 管理台，既可以用自然语言完成采购任务，
也可以直接在业务页面中管理报价、订单、库存、补货、退货、审批与账号权限。

## 项目边界

| 范围 | 当前实现 |
|---|---|
| 采购对象 | 汽车与摩托车零部件 |
| 供应链目录 | 零部件、供应商、多供应商报价、MOQ、交期、质量评分 |
| 适配数据 | 摩托车车型档案与零部件适配关系，仅用于选件和采购校验 |
| 采购执行 | 建单、审核、采购中、整单收货入库、取消和待处理订单过期 |
| 库存 | 手工入库/出库、库存 CAS、不可变库存流水、库存预警 |
| 补货 | 基于安全库存、目标倍数和最小采购量的确定性补货任务 |
| 退货 | 已入库采购单的轻量退货申请与库存扣减 |
| 不包含 | 整车采购、整车销售、零售客户、电商页面、生产制造和复杂售后结算 |

车型数据只承担零部件适配查询，不代表系统在采购整车。当前采购退货也不包含质检、
供应商结算、退款和复杂售后流程。

## 核心能力

### 1. 对话式采购 Agent

- 主 Agent 负责简单查询、任务编排和结果整合。
- 采购分析子 Agent 负责跨来源取数、供应商对比、库存与订单分析、图表和文档生成。
- 采购订单子 Agent 负责订单、收货、补货和退货等多步骤业务流程。
- 子 Agent 使用 YAML 精确声明工具白名单与输出契约，不能通过模糊名称扩大权限。
- FastMCP 将供应商、零部件、采购目录、订单、库存、补货和退货接口封装为 Agent 工具。

### 2. Harness 四阶段执行

每轮业务请求经过 Planning、Executing、Review、Result 四个结构化阶段：

~~~text
用户请求或 HITL 恢复
  └─ Planning：识别任务类型并形成计划
      └─ Executing：主 Agent 直调工具或委派子 Agent
          └─ Review：规则优先，模糊场景由 Router LLM 判定
              ├─ 只读任务：允许定向返工，最多 3 轮
              ├─ 写入/委派任务：只审查一次，不自动重放副作用
              └─ Result：校验事实、回执与最终声明
~~~

ReviewPolicy 会根据任务类型、工具数量、写操作、委派、失败信号和多来源证据决定是否评审。
具体 Rubric 固定在 harness_config.yaml 中，LLM 只参与路由和评分，不动态发明验收标准。

### 3. 零部件采购闭环

Java ERP 已完成四个采购里程碑：

| 阶段 | 能力 |
|---|---|
| M1 采购目录 | 一个零件对应多个供应商报价；维护采购价、MOQ、交期、质量评分、默认供应商、车型与适配关系 |
| M2 收货与库存流水 | 手工入出库和采购收货统一经过事务命令；整单收货同时更新库存、流水、订单状态和实际到货日期 |
| M3 确定性补货 | 定时或手动巡检低库存，按安全库存倍数和 MOQ 计算补货量；可由补货任务创建并关联采购单 |
| M4 采购退货 | 对已入库订单明细创建退货；确认时校验累计退货量、扣减库存并记录 PURCHASE_RETURN 流水 |

库存正确性始终由 MySQL 事务和条件更新保证。Redis 只用于零件/供应商查询缓存、
登录限流和最近/常用访问，不承担库存、订单、审批或 Agent 记忆的权威状态。

### 4. 写操作治理

所有受保护的 ERP 写工具共享同一套审批、审计与幂等策略：

~~~text
Agent 发起 ERP 写工具
  └─ 校验 JWT 权限与 ApprovalPolicy
      └─ 创建 operation_id、payload_hash 和审批任务
          ├─ 拒绝：记录 REJECTED，不调用 ERP
          └─ 批准：预登记写审计并调用 ERP
                  ├─ 明确成功/失败：保存终态与追加式事件
                  └─ 结果未知：只读查询 operation 或幂等键
                                └─ 自动对账或进入 MANUAL_REQUIRED
~~~

- 申请人与审批人分离，申请人不能在自己的会话中批准写操作。
- thread_id + tool_call_id 生成稳定幂等键，ERP 另以 operationId 和订单 idempotencyKey 防重。
- DISPATCHING、UNKNOWN 和 RECONCILING 状态只允许查询与对账，禁止自动重放原写请求。
- audit.write_audit_events 为 append-only，数据库触发器拒绝更新和删除。
- Result 阶段要求所有“已写入”声明必须有真实回执，失败后不得继续声称成功。

### 5. 统一身份与权限

Java ERP 是唯一身份源和令牌签发方：

- 使用 RS256 签发短期 Access Token，Refresh Token 保存在 HttpOnly、SameSite=Strict Cookie。
- Java ERP、Python Backend 和 MCP 分别校验签名、issuer、audience 与权限。
- Backend 每次入口请求向 Java ERP 校验账号状态和 authz_version，停用账号或改权后旧令牌立即失效。
- 内置 ADMIN、PURCHASER、WAREHOUSE、VIEWER 角色，并支持用户、角色和权限管理。
- ERP 控制器使用明确的 permission code；助手写操作还要求 assistant:erp-write。
- 会话、下载文件、记忆、审计和沙箱均绑定 JWT subject，客户端传入的 user_id 不作为身份来源。

### 6. 记忆、知识与上下文

- HOT：LangGraph Checkpoint 保存当前会话的可恢复工作流状态。
- WARM：请求开始或 HITL resume 时生成稳定偏好和近期任务快照。
- COLD：PostgreSQL zhparser 全文检索与 pgvector 语义检索并行召回，再通过 RRF 融合。
- Semantic、Episodic、Procedural 和 Org Policy 使用独立命名空间并按用户隔离。
- 长对话达到模型上下文窗口的配置阈值后，采购专用压缩器会总结旧消息并保留最近上下文。
- 采购知识库支持入库、证据跟踪、去重、重排和有界补搜。

### 7. 安全沙箱

- 每个用户使用独立 Docker 沙箱和工作目录，支持预热池、租约、空闲回收与故障重建。
- 沙箱启用只读根文件系统、tmpfs、资源限制、Capability 裁剪、seccomp 和 PID 限制。
- Backend 通过独立 Docker-in-Docker daemon 管理沙箱，不直接挂载宿主机 Docker socket。
- 3 次基础设施失败会打开 60 秒熔断；generation 变化后重新同步基础 Skills 和用户 Skills。
- 容器部署默认关闭沙箱直连 MCP，避免把用户访问令牌注入可执行模型生成代码的环境。

### 8. 四维评测

评测通过真实 SSE 对话、Harness Trace、MCP 工具调用、ERP 终态、审批和写审计采集证据，
固定输出四个独立维度，不计算加权总分：

| 维度 | 核心指标 |
|---|---|
| 轨迹 | 轨迹通过率、工具调用准确率 |
| 业务质量 | 任务完成率、关键事实准确率、采购建议可行率、补货数量偏差 |
| 安全 | 风险操作拦截率、合法写入误拦截率 |
| 稳定性 | pass^3、故障恢复率 |

模型只负责从回答中抽取结构化声明，最终判分由确定性规则、ERP 状态和审计证据完成。

### 9. 可观测性与交付

- Backend、MCP、Java ERP 使用 W3C Trace Context 串联请求。
- OpenTelemetry Collector 接收 OTLP Trace，Tempo 存储，Grafana 提供检索与 Dashboard。
- Prometheus 采集 Backend 和 Java ERP 指标，Alertmanager 按 critical/warning 分级路由。
- alert-webhook 支持钉钉和 SMTP；未配置通知渠道时只记录结构化日志。
- Python 与 Java 日志均输出单行 JSON，并包含 trace.id、span.id。
- GitHub Actions 覆盖密钥扫描、代码质量、测试、镜像构建、集成栈、数据库恢复和发布门禁。

## 系统架构

~~~mermaid
flowchart LR
    USER[Browser] --> NGINX[Nginx :80/:443]
    NGINX --> WEB[Next.js ERP + Assistant]
    NGINX -->|/api/auth /api/erp| ERP[Java ERP]
    NGINX -->|/api/chat /api/history /api/write-audit| API[FastAPI Backend]

    API --> AGENT[Procurement Main Agent]
    AGENT --> HARNESS[Planning → Executing → Review → Result]
    AGENT -->|task| ANALYST[Procurement Analyst]
    AGENT -->|task| ORDER[Procurement Order]
    AGENT --> MCP[FastMCP Gateway]
    ANALYST --> MCP
    ORDER --> MCP
    MCP --> ERP

    ERP --> MYSQL[(MySQL)]
    ERP --> REDIS[(Redis)]
    API --> PG[(PostgreSQL + pgvector + zhparser)]
    API --> DIND[Docker-in-Docker]
    DIND --> BOX[Per-user Sandbox]

    API --> OTEL[OTel Collector]
    MCP --> OTEL
    ERP --> OTEL
    OTEL --> TEMPO[Tempo]
    API --> PROM[Prometheus]
    ERP --> PROM
    PROM --> ALERT[Alertmanager]
    ALERT --> HOOK[Alert Webhook]
    PROM --> GRAFANA[Grafana]
    TEMPO --> GRAFANA
~~~

## 数据权威边界

| 数据 | 权威存储 |
|---|---|
| 供应商、零部件、报价、车型适配、订单、库存、补货、退货、账号与 RBAC | MySQL / Java ERP |
| Agent 会话、Checkpoint、长期记忆、知识库、运行租约、审批与写审计 | PostgreSQL |
| 零件/供应商缓存、登录限流、最近和常用访问 | Redis |
| 临时图表、文档和下载文件 | Backend artifact-data 卷，按用户和 TTL 隔离 |
| Trace | Tempo |
| 指标与告警状态 | Prometheus / Alertmanager |

## 技术栈

| 层次 | 技术 |
|---|---|
| Agent | Python 3.11、DeepAgents 0.7.35、LangGraph 1.2+、LangChain |
| API / MCP | FastAPI、FastMCP 3.4.11、HTTPX、SSE |
| ERP | Spring Boot 3.1.10、JDK 17、MyBatis-Plus、Flyway |
| 数据 | PostgreSQL 16、pgvector、zhparser、MySQL 8、Redis 7 |
| 前端 | Next.js 16.2、React 19.2、TypeScript、Tailwind CSS 4 |
| 沙箱 | Docker SDK、Docker-in-Docker、seccomp、用户级租约 |
| 可观测性 | OpenTelemetry、Tempo、Prometheus、Grafana、Alertmanager |
| 交付 | Docker Compose、Nginx、GitHub Actions、Release Please |

## 目录结构

~~~text
AutoSupply-Agent/
├─ src/
│  ├─ agent/
│  │  ├─ main_agent.py             主 Agent、工具、子 Agent 和中间件组装
│  │  ├─ harness.py                四阶段状态与 Harness 中间件
│  │  ├─ review_policy.py          规则优先、模型兜底的评审路由
│  │  ├─ harness_config.yaml       阶段、任务类型和固定 Rubric
│  │  ├─ approval.py               写工具审批策略唯一来源
│  │  ├─ audit/                    写审计、补偿对账和结果审计
│  │  ├─ backends/                 Docker 沙箱、预热池和 Proxy
│  │  ├─ middlewares/              评审、写治理、记忆、Skills、沙箱中间件
│  │  ├─ subagents/                采购分析与订单子 Agent 配置
│  │  ├─ memory/                   Semantic / Episodic / Procedural 记忆
│  │  ├─ knowledge/                采购知识检索、证据、RRF 与有界补搜
│  │  └─ tools/                    图表、文档、知识、记忆、下载和 HITL 工具
│  ├─ api_view/                    FastAPI、SSE、JWT、历史、审批和审计 API
│  ├─ mcp_server/                  ERP JWT 网关和采购 MCP 工具
│  ├─ evaluation/                  四维评测 Runner、Oracle 与报告
│  ├─ observability/               OpenTelemetry 初始化与告警 Webhook
│  ├─ skills/                      Agent Skills
│  ├─ runtime_state.py             PostgreSQL 运行租约与所有权
│  ├─ artifacts.py                 用户隔离临时文件与 TTL 清理
│  └─ database.py                  PostgreSQL Schema 与检索索引初始化
├─ frontend/
│  └─ src/app/                     助手、ERP、补货、退货、审计和权限页面
├─ java_erp/
│  ├─ src/main/java/               采购 ERP、身份权限和事务服务
│  └─ src/main/resources/db/       Flyway V1–V10 迁移
├─ deploy/
│  ├─ postgres/                    pgvector + zhparser 镜像
│  ├─ sandbox/                     预装数据分析依赖的沙箱镜像
│  ├─ nginx/                       统一入口、TLS 与反向代理
│  ├─ tempo/ / otel-collector/     Trace 采集与存储
│  ├─ prometheus/ / grafana/       指标、告警规则与 Dashboard
│  ├─ alertmanager/                告警聚合、抑制与分级路由
│  ├─ ci/ / cd/ / runner/          集成门禁、发布、回滚和 Runner
│  ├─ dr/ / mysql/                 双数据库备份恢复与迁移
│  └─ cloud/                       新云主机初始化
├─ migrations/postgres/            PostgreSQL 版本化迁移
├─ docker-compose.yml              完整生产拓扑
├─ eval.md                         四维评测口径
└─ tenant.md                       多用户隔离与共享 Agent 迁移设计
~~~

## 环境要求

- Docker Engine 24+ 与 Docker Compose v2。
- 至少 4 GB 可用内存；增加沙箱预热池时需要同步增加资源。
- 可访问 OpenAI-compatible LLM 的 API Key。
- Linux 服务器建议使用 ext4，或启用 ftype=1 的 xfs。
- 本地分进程开发另需 Python 3.11、Node.js 22、npm 10+、JDK 17–21 和 Maven Wrapper。

## 快速启动

Docker Compose 会启动 PostgreSQL、MySQL、Redis、Java ERP、MCP、Backend、Frontend、
Docker 沙箱、Tempo、OpenTelemetry Collector、Prometheus、Alertmanager、Grafana 和 Nginx。

### 1. 准备配置

~~~bash
git clone https://github.com/lyrwazbzh/AutoSupply-Agent.git
cd AutoSupply-Agent

cp deploy/.env.example deploy/.env
cp deploy/nginx.env.example deploy/nginx.env
~~~

编辑 deploy/.env，至少完成以下配置：

- 填写 CHATANYWHERE_API_KEY 和正确的 PUBLIC_BASE_URL。
- 替换 PostgreSQL、MySQL 和 Redis 的所有占位口令。
- 按需选择 LLM_MODEL 与 LLM_BASE_URL。
- 生产环境设置 Grafana 密码、告警渠道和 TLS。

### 2. 生成 JWT 密钥和初始管理员

~~~bash
bash deploy/init-security.sh
~~~

脚本会生成 RS256 密钥，并在未指定密码时打印一次性管理员密码。首次登录后应立即修改密码，
再清空 deploy/.env 中的 ERP_BOOTSTRAP_ADMIN_USERNAME 和 ERP_BOOTSTRAP_ADMIN_PASSWORD。

### 3. 准备 TLS 文件

Nginx 配置始终加载证书路径，因此即使本地只使用 HTTP，也需要一组占位证书：

~~~bash
mkdir -p deploy/nginx/tls
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout deploy/nginx/tls/key.pem \
  -out deploy/nginx/tls/cert.pem \
  -subj '/CN=localhost'
chmod 600 deploy/nginx/tls/key.pem
~~~

生产环境应在 deploy/nginx.env 中设置 TLS_ENABLED=1，并替换为可信证书。

### 4. 启动与验收

~~~bash
docker compose config
docker compose up -d --build
docker compose ps
curl http://localhost/healthz
~~~

- 管理台与智能助手：http://localhost/
- Grafana：http://localhost:13000/
- Java ERP Swagger UI 仅在可访问 ERP 内部端口的开发环境使用。

首次启动时：

- Flyway 按 V1–V10 创建或升级 MySQL Schema。
- Backend 创建 PostgreSQL 应用、知识、审批、审计和运行租约结构。
- LangGraph 创建 Checkpoint 与 Store 表。
- sandbox-image-loader 在 DinD 中构建预装分析依赖的沙箱镜像。

## 本地分进程开发

### Python 与前端

~~~bash
python -m venv .venv

# Linux / WSL
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install -r requirements-dev.txt
cp .env.example .env

cd frontend
npm ci
cd ..
~~~

本地需要 PostgreSQL 16（含 pgvector 与 zhparser）、MySQL 8、Redis 和可用的 Docker daemon。
建议复用 deploy 目录中的镜像与配置。

### 启动服务

~~~bash
# 终端 1：Java ERP
cd java_erp
./mvnw spring-boot:run

# 终端 2：MCP
python -m src.mcp_server.server_main

# 终端 3：Backend
python -m src.api_view.web_main

# 终端 4：Frontend
cd frontend
npm run dev
~~~

本地默认地址：

| 服务 | 地址 |
|---|---|
| Frontend | http://localhost:3000 |
| Backend | http://localhost:8000 |
| MCP | http://localhost:9000 |
| Java ERP | http://localhost:8080 |

Mock ERP 仅由 deploy/ci/compose.mock-erp.yml 启动，用于隔离契约测试，不作为联调或生产实现。

## 关键配置

| 配置 | 作用 |
|---|---|
| CHATANYWHERE_API_KEY / LLM_MODEL / LLM_BASE_URL | 主 Agent、Router、Grader 和联网工具使用的模型 |
| DATABASE_URL | PostgreSQL、LangGraph、记忆、知识、租约与审计 |
| ERP_BASE_URL | Java ERP 地址 |
| MCP_SERVER_URL | Backend 访问 MCP 的地址 |
| AUTH_MODE / JWT_* | Backend JWT Resource Server 配置 |
| MCP_AUTH_ENABLED / MCP_JWT_AUDIENCE | MCP JWT 校验 |
| ERP_REPLENISHMENT_* | 补货巡检开关、Cron、时区和目标库存倍数 |
| SANDBOX_IMAGE / SANDBOX_WARM_POOL_SIZE | 沙箱镜像和预热池 |
| MEMORY_* | WARM/COLD 记忆保留与召回策略 |
| OTEL_* | Trace 服务名、Collector 地址和采样率 |
| ALERT_* | 钉钉与 SMTP 告警渠道 |
| ARTIFACT_TTL_SECONDS | 用户临时产物保留时间 |

容器部署只读取 deploy/.env；项目根目录 .env 只用于本地分进程开发。

## Backend 关键接口

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | /api/chat/stream | 创建或继续会话，以 SSE 返回阶段、Token、工具和中断事件 |
| POST | /api/chat/{thread_id}/resume | 提交补充信息或消费已落库审批结果并恢复工作流 |
| GET | /api/chat/{thread_id}/state | 查询中断与待处理状态 |
| GET | /api/chat/{thread_id}/history | 获取当前用户的会话消息 |
| GET / DELETE | /api/history / /api/history/{thread_id} | 查询或删除当前用户会话 |
| GET | /api/write-audit | 查询当前用户写操作 |
| GET | /api/write-audit/approval-queue | 管理员查看独立审批队列 |
| POST | /api/write-audit/approvals/{operation_id}/decision | 管理员批准或拒绝写操作 |
| GET / POST | /api/write-audit/manual-queue / {operation_id}/resolve-manual | 查询并处理人工对账 |
| GET | /api/evaluation/metrics | 获取最新四维评测报告 |
| GET | /api/evaluation/traces/{thread_id} | 读取有归属校验的 Harness Trace |
| GET | /api/download/{file_id}/{filename} | 下载当前用户 TTL 内的临时产物 |
| GET | /metrics | Prometheus 指标 |
| GET | /health | Backend 健康检查 |
| GET | /healthz | Nginx 存活检查 |

主要 SSE 事件包括 thinking、phase、todo_update、token、tool_start、tool_args、
tool_result、tool_end、review_result、interrupt、error 和 done。

## MCP 工具范围

| 工具组 | 主要能力 |
|---|---|
| 供应商 | 搜索、分页、详情、新增、状态变更 |
| 零部件 | 查询、分页、按供应商查询、新增 |
| 采购目录 | 供应商报价、车型查询、适配查询、按车型反查零件 |
| 订单 | 建单、修改、查询、统计、状态变更、幂等键回查 |
| 收货与库存 | 整单收货、库存预警、盘点、入出库、库存流水 |
| 补货 | 查询、创建、巡检、生成采购单、完成、取消 |
| 采购退货 | 查询、创建、确认 |

写工具会传递 operationId、X-Operation-Id、Bearer Token 和 Trace Context。

## 评测

校验数据集 Schema：

~~~bash
python -m src.evaluation \
  --dataset src/test/evaluation/datasets/schema_examples.jsonl \
  --validate-only
~~~

运行评测测试：

~~~bash
pytest -q \
  src/test/test_evaluation_oracle.py \
  src/test/test_evaluation_runner.py \
  src/test/test_evaluation_dimensions.py
~~~

正式评测支持按 trajectory、business、safety、stability 选择维度，并通过独立评测环境执行
Fixture 重置、ERP 探针和故障注入。完整口径见 [eval.md](eval.md)。

## 测试与质量门禁

~~~bash
# Python
ruff check .
python -m compileall -q src
pytest -v --cov --cov-report=term-missing

# Java ERP
cd java_erp
./mvnw -B -ntp verify

# Frontend
cd frontend
npm run typecheck
npm run lint
npm run test
npm run build
~~~

CI 还会执行：

- Workflow 权限与触发安全检查。
- Gitleaks 全历史密钥扫描和敏感路径检查。
- PostgreSQL 与 MySQL 迁移、备份、恢复和负向用例。
- Mock ERP 契约回归与 Java ERP 真实链路冒烟。
- Nginx 认证路径、完整 Compose 拓扑和真实沙箱冒烟。
- Backend、Frontend、PostgreSQL、Java ERP 镜像构建。
- 发布、观察窗、状态检查和回滚能力验证。

## 可观测性

完整链路：

~~~text
Backend ──traceparent──> MCP ──traceparent──> Java ERP
   └──────────── OTLP/HTTP ────────────────┘
                         ↓
                  OTel Collector
                         ↓
                       Tempo ──> Grafana

Backend / Java ERP ──metrics──> Prometheus ──> Alertmanager
                                                   ├─ warning：钉钉
                                                   └─ critical：钉钉 + 邮件
~~~

Grafana 预置 ERP Agent Overview Dashboard 和 Prometheus、Tempo 数据源。告警排查流程见
[deploy/observability/RUNBOOK.md](deploy/observability/RUNBOOK.md)。

## 当前工程边界

- 采购收货只支持整单入库，不支持部分收货。
- 采购退货不包含质检、供应商结算、退款和复杂售后。
- 多副本运行时，AgentSession、执行租约、沙箱分配和暖池归属已外置 PostgreSQL；
  临时产物仍需要粘性下载路由或共享 Artifact 存储。
- 共享 DinD 是沙箱基础设施单点，且 privileged DinD 只适合受控网络，不等同于强安全边界。
- 沙箱直连 MCP 默认关闭；Agent 主进程仍通过受认证的 MCP 客户端访问 ERP。
- Mock ERP 仅用于 CI 契约测试。
- 生产环境必须使用 TLS、强数据库口令、独立 Grafana 密码和受保护的 JWT 私钥。

## 文档索引

- [完整部署、认证与故障排查](deploy/README.md)
- [Java ERP 业务、数据库与写契约](java_erp/README.md)
- [Java ERP API 文档](java_erp/docs/API_DOCUMENTATION.md)
- [四维评测方案](eval.md)
- [可观测性 Runbook](deploy/observability/RUNBOOK.md)
- [云主机初始化](deploy/cloud/README.md)
- [CI 集成栈](deploy/ci/README.md)
- [构建、发布与回滚](deploy/cd/README.md)
- [双数据库备份、恢复与演练](deploy/dr/README.md)
- [宿主 MySQL 迁移](deploy/mysql/README.md)
- [Runner 安装与权限边界](deploy/runner/README.md)
- [PostgreSQL 迁移说明](migrations/README.md)

## 相关项目

- [DeepAgents](https://github.com/langchain-ai/deepagents)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [Model Context Protocol](https://modelcontextprotocol.io/)
