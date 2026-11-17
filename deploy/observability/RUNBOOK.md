# ERP Agent 可观测性 Runbook

## 组件与数据流

```text
Backend ──traceparent──> MCP ──traceparent──> Java ERP
   │                       │                      │
   └──────── OTLP/HTTP ────┴──────────────────────┘
                         │
                  OTel Collector ──OTLP/gRPC──> Tempo ──> Grafana

Backend / Java ERP ──metrics──> Prometheus ──alerts──> Alertmanager
                                                        │
                                           critical: 钉钉 + 邮件
                                           warning:  钉钉
```

应用日志写入容器 stdout，Python 与 Java 均为单行 JSON。`trace.id`、`span.id`
用于从日志跳转至 Tempo Trace，不部署 Elastic 日志平台。

## 启动检查

1. `docker compose ps` 确认 `tempo`、`otel-collector`、`prometheus`、
   `alertmanager`、`grafana`、`alert-webhook` 已启动。
2. Grafana 的 Prometheus 数据源访问 `http://prometheus:9090`，Tempo 数据源访问
   `http://tempo:3200`；两者与 Grafana 均连接 `observability` 网络。
3. 打开 `ERP Agent Overview`，确认 `Core Services Up` 为 `1`。
4. 发起一次采购查询，在 Trace 面板筛选 `erp-agent-backend`，确认链路包含
   Backend、MCP、Java ERP 三个服务。

## Trace 与日志定位

1. Grafana Explore 选择 Tempo，使用 TraceQL：
   ``{ resource.service.name =~ `erp-agent-.*` }``。
2. 从异常 Span 复制 Trace ID。
3. 查看对应服务日志并按 `trace.id` 过滤；同一 Trace ID 应覆盖 Backend、MCP、
   Java ERP。ERP 写审计同时保存 MCP 传入的 `X-Trace-ID`。
4. 无下游 Span 时依次检查：请求是否携带 `traceparent`、Collector 是否可达、
   Tempo 是否可写、应用是否配置 `OTEL_EXPORTER_OTLP_ENDPOINT`。

## 告警分级

- `critical / P0`：Alertmanager 10 秒聚合，钉钉与邮件同时通知，30 分钟重复提醒。
- `warning / P1`：Alertmanager 30 秒聚合，仅钉钉通知，4 小时重复提醒。
- critical 与 warning 同时出现时抑制相同服务、相同告警的 warning 通知。
- 恢复通知由 Alertmanager 的 `send_resolved` 统一发送。

## ERP write needs manual reconciliation

1. 在 Grafana 查看 `ERP Write Reconciliation` 的 `manual_required` 增量。
2. 从写审计记录取得 `operation_id`、`thread_id` 与 `trace_id`。
3. 依据 ERP 终态人工确认是否已经生效，禁止直接重放未知终态写操作。
4. 调用人工结案接口记录处理结果。

## ERP write reconciliation repeatedly deferred

1. 检查 Java ERP `/actuator/health/readiness` 与 Backend 到 ERP 的 Trace。
2. 检查 ERP 操作查询接口是否持续超时或返回非确定状态。
3. 恢复依赖后等待下一轮对账；达到最大尝试次数后按人工对账处理。

## ERP write reconciliation worker error

1. 检查 PostgreSQL 健康状态与 Backend 数据库连接日志。
2. 确认 `audit.reconcile_jobs` 可读写且无迁移异常。
3. 恢复后观察 `worker_error` 是否停止增长，再处理积压任务。

## ERP write audit persistence failure

1. 优先确认写请求是否已被阻断；若 ERP 终态未知，不得自动重放。
2. 检查 PostgreSQL 容量、连接数、事务错误与审计表状态。
3. 按 Trace ID 对齐 Backend、MCP、ERP 日志，确认实际业务终态。
4. 恢复审计持久化后完成补偿记录或人工结案。

## 通知故障

1. 检查 `alertmanager` 日志确认路由和 webhook 投递状态。
2. 检查 `alert-webhook` 日志确认钉钉或 SMTP 返回结果。
3. warning 未发邮件属于既定策略；critical 应同时产生钉钉与邮件结果。
4. 未配置通知渠道时 webhook 仅写 JSON 日志，不阻断 Alertmanager。
