# java-erp（摩托车零部件采购管理系统）

## 项目介绍

这是一个基于 Spring Boot 的摩托车零部件采购管理系统，用于管理供应商、产品/零部件、采购订单、库存、客户和物流等业务。

本目录位于 `Agent-Harness-main/java_erp`，作为 Agent-Harness 的 Java ERP 后端：MCP Server 通过 `ERP_BASE_URL`（默认 `http://localhost:8080`）调用本服务的 `/api/*` 接口。

### 主要功能

- **供应商管理**：管理供应商信息，包括信用评级、合作状态等
- **产品管理**：管理摩托车零部件信息，包括分类、采购价格等
- **采购订单**：管理采购订单的全流程，包括创建、审核、入库等
- **库存管理**：管理库存，包括入库、出库、预警等功能
- **客户管理**：管理客户信息，包括客户类型、折扣等级等
- **物流管理**：管理物流信息，跟踪货物运输状态
- **统计分析**：提供采购统计、库存预警等分析报表

### 与 Agent-Harness MCP 对齐

MCP 四组工具直接映射到下列 REST 路径（统一响应 `{code,message,data}`）：

| MCP 工具组 | 主要路径 |
|------------|----------|
| suppliers | `/api/suppliers/search`、`/page`、`/get/{id}`、`/create`、`/update-status/{id}` |
| parts | `/api/parts/get/{id}`、`/search`、`/supplier/{id}`、`/page`、`/create` |
| orders | `/api/orders/create`、`/update/{id}`、`/page`、`/get/{id}`、`/search-details`、`/statistics`、`/update-status/{id}`、`/by-idempotency` |
| inventory | `/api/inventory/warning`、`/page`、`/check`、`/inbound`、`/outbound`、`/get/{id}` |

客户、物流、统计等接口仍由本系统提供，当前 Harness MCP 未挂载对应工具组。写治理相关的 `operationId` 回查、订单幂等等能力按仓库 plan 后续在本工程补齐。

## 技术栈

| 技术 | 版本 |
|------|------|
| Spring Boot | 3.1.10 |
| JDK | 17 |
| MyBatis Plus | 3.5.3.1 |
| MySQL | 8.0 |
| Lombok | 1.18.30 |
| springdoc-openapi | 2.0.2 |
| Hutool | 5.8.25 |

## 快速开始

### 环境要求

- JDK 17+
- MySQL 8.0+
- Maven 3.6+

### 数据库配置

1. 创建数据库（系统会自动创建，也可以手动创建）：

```sql
CREATE DATABASE motorparts_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

2. 修改配置文件 `src/main/resources/application.yml` 中的数据库连接信息：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/motorparts_db?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai
    username: root
    password: 123456
```

### 构建项目

```bash
# 进入项目目录（仓库内路径）
cd java_erp

# 编译项目
mvn clean compile

# 运行项目
mvn spring-boot:run
```

### 访问地址

- **系统首页**：http://localhost:8080
- **API文档**：http://localhost:8080/swagger-ui.html

### 对接 Agent-Harness

在仓库根目录 `.env` 中配置：

```bash
ERP_BASE_URL=http://localhost:8080
```

建议启动顺序：MySQL → `java_erp` → MCP（`:9000`）→ backend → frontend。

```bash
# 终端 1：本服务
cd java_erp && mvn spring-boot:run

# 终端 2：MCP
cd .. && python -m src.mcp_server.server_main

# 终端 3：Backend
python -m src.api_view.web_main
```

Compose 全栈默认使用 `deploy/mock-erp:8081`；本地联调本服务时保持 `ERP_BASE_URL=http://localhost:8080`。

## 项目结构

```
src/main/java/com/motorparts/
├── MotorpartsApplication.java          # 启动类
├── config/                              # 配置类
│   ├── MyBatisPlusConfig.java
│   ├── WebMvcConfig.java
│   ├── SwaggerConfig.java
│   └── DdlApplicationRunnerConfig.java
├── controller/                          # 控制器层
│   ├── SupplierController.java
│   ├── PartController.java
│   ├── PurchaseOrderController.java
│   ├── InventoryController.java
│   ├── CustomerController.java
│   ├── LogisticsController.java
│   └── StatisticsController.java
├── service/                              # 服务层
│   ├── SupplierService.java
│   ├── PartService.java
│   ├── PurchaseOrderService.java
│   ├── InventoryService.java
│   ├── CustomerService.java
│   ├── LogisticsService.java
│   └── impl/                             # 实现类
├── mapper/                               # Mapper接口
├── entity/                               # 实体类
├── dto/                                  # 数据传输对象
├── common/                               # 通用类
│   ├── Result.java
│   ├── PageResult.java
│   ├── enums/
│   └── exception/
└── init/                                 # 数据初始化
    ├── DatabaseInitializer.java
    └── SparkPlugDataInitializer.java
```

## 数据初始化

项目启动时会自动执行数据初始化，包括：

- 创建数据库表结构
- 插入模拟数据（约30个供应商、60个产品、120个订单等）

### 初始化配置

在 `application.yml` 中配置：

```yaml
motorparts:
  init:
    enabled: true          # 是否启用数据初始化
    insert-sample-data: true  # 是否插入模拟数据
```

### 模拟数据说明

- **供应商**：30条，包含Bosch、DENSO、Brembo等知名品牌
- **产品**：60条，包含发动机类、车架类、电气类等分类
- **采购订单**：120条，时间范围2024年至今
- **客户**：40条，包含经销商、零售店、个人用户
- **用户**：12条，包含管理员、采购员、仓管员、销售员
- **库存**：60条，与产品一一对应
- **物流**：80-100条，与已发货订单关联

## API接口测试

### 使用Swagger UI测试

1. 启动项目后访问：http://localhost:8080/swagger-ui.html
2. 在页面上可以看到所有API接口
3. 点击任意接口可以查看详情和测试

### 使用Postman测试

1. 导入API文档或手动添加接口
2. 基础URL：`http://localhost:8080/api`
3. 示例请求：

**创建供应商**
```http
POST http://localhost:8080/api/suppliers
Content-Type: application/json

{
  "supplierCode": "SUP00031",
  "name": "测试供应商",
  "contactPerson": "张三",
  "phone": "13800138000",
  "email": "test@example.com",
  "address": "上海市某区某路1号",
  "creditRating": "A",
  "status": 1
}
```

**分页查询**
```http
GET http://localhost:8080/api/suppliers/page?current=1&size=10
```

## 数据库设计

### 表结构

| 表名 | 说明 | 关联关系 |
|------|------|----------|
| supplier | 供应商表 | - |
| part | 产品/零部件表 | supplier_id -> supplier |
| purchase_order | 采购订单表 | supplier_id -> supplier, created_by -> user |
| order_detail | 订单明细表 | order_id -> purchase_order, part_id -> part |
| inventory | 库存表 | part_id -> part |
| customer | 客户表 | - |
| user | 用户表 | - |
| logistics | 物流表 | order_id -> purchase_order |
| erp_operation | 写操作回查表 | operation_id PK |
| order_idempotency | 订单幂等绑定表 | idempotency_key PK → order_id |
| local_message | 本地消息表（延迟取消/旁路） | msg_key 唯一；status + deliver_at |

### 主要字段

- 所有表都包含 `deleted`（逻辑删除）、`create_time`、`update_time` 字段
- 金额字段使用 DECIMAL 类型确保精度
- 时间字段使用 DATETIME 类型
- `purchase_order` 另含可空列 `idempotency_key`、`payload_hash`（Harness 写单）
- 迁移脚本：`docs/migrations/2026_harness_compat.sql`（启动时 `HarnessCompatMigrationRunner` 自动执行）

## Harness 写治理冒烟

```bash
# 1) 幂等建单（两次同 key 应返回同一订单）
curl -s -X POST http://localhost:8080/api/orders/create \
  -H "Content-Type: application/json" -H "X-Operation-Id: op-smoke-1" \
  -d "{\"orderNumber\":\"PO-SMOKE-1\",\"status\":0,\"idempotencyKey\":\"idem-smoke-1\",\"totalAmount\":51,\"orderDetail\":[{\"partId\":1,\"quantity\":2,\"unitPrice\":25.5}]}"

curl -s -X POST http://localhost:8080/api/orders/create \
  -H "Content-Type: application/json" -H "X-Operation-Id: op-smoke-1b" \
  -d "{\"orderNumber\":\"PO-SMOKE-1\",\"status\":0,\"idempotencyKey\":\"idem-smoke-1\",\"totalAmount\":51,\"orderDetail\":[{\"partId\":1,\"quantity\":2,\"unitPrice\":25.5}]}"

# 2) 同 key 不同明细 → body.code=409
curl -s -X POST http://localhost:8080/api/orders/create \
  -H "Content-Type: application/json" \
  -d "{\"orderNumber\":\"PO-SMOKE-2\",\"idempotencyKey\":\"idem-smoke-1\",\"totalAmount\":100,\"orderDetail\":[{\"partId\":1,\"quantity\":4,\"unitPrice\":25}]}"

# 3) operation 回查
curl -s http://localhost:8080/api/operations/op-smoke-1

# 4) 幂等键回查
curl -s "http://localhost:8080/api/orders/by-idempotency?idempotencyKey=idem-smoke-1"
```

业务错误保持 **HTTP 200 + body.code**（含 409/404），与 Mock / MCP 一致。订单 `status=0` 写库前归一为 `1`；供应商历史 `status=0` 归一为 `2`。

一键冒烟（服务已启动）：

```powershell
powershell -File scripts/smoke_harness.ps1
# 再于 MySQL 执行 docs/verify_invariants.sql
```

### Campus-Dash 工程模式（已落地）

| 模式 | 落点 |
|------|------|
| 幂等键 + 唯一索引 | `order_idempotency` / `purchase_order.uk_idempotency_key` |
| 同键不同 payload → 409 | `payload_hash` 比对 |
| 状态 / 库存 CAS | 订单与供应商 `WHERE status=from`；出库 `qty>=?` |
| 回查可验证 | `/api/operations/{id}`、`/api/orders/by-idempotency` |
| 不变式验收 | `scripts/smoke_harness.ps1` + `docs/verify_invariants.sql` |

### Redis Lua / RocketMQ（可开关）

| 开关 | 默认 | 作用 |
|------|------|------|
| `motorparts.redis.enabled` | false | 出库热路径 Lua 扣减；失败回滚；正确性底线是 MySQL CAS |
| `motorparts.mq.enabled` | true | `local_message` + 定时扫描：待审核订单到期自动取消 |
| `motorparts.mq.rocketmq-enabled` | false | 旁路推 RocketMQ（需去掉 autoconfigure exclude 并配置 nameserver）；Harness 仍以 `/api/operations` 为回查源 |

开启 Redis 示例：

```yaml
motorparts:
  redis:
    enabled: true
spring:
  data:
    redis:
      host: localhost
      port: 6379
```

## 注意事项

1. **首次运行**：首次运行时会自动创建表结构和插入模拟数据
2. **重新初始化**：如果需要重新插入数据，可以先删除数据库中的数据，或设置 `motorparts.init.recreate-tables: true`
3. **API测试**：建议使用Swagger UI进行API测试
4. **密码说明**：用户密码已加密存储，默认密码为 `admin123`
5. **Harness 联调**：MCP / reconciler 依赖本服务可达；改端口时同步修改根目录 `.env` 的 `ERP_BASE_URL`

## 默认用户

| 用户名 | 密码 | 角色 | 部门 |
|--------|------|------|------|
| admin | admin123 | 管理员 | 财务部 |
| user1 | admin123 | 采购员 | 采购部 |
| user2 | admin123 | 仓管员 | 仓储部 |
| user3 | admin123 | 销售员 | 销售部 |

## 文档

- [API接口文档](docs/API_DOCUMENTATION.md)
- [数据库表结构](docs/database_schema.sql)
- [数据来源说明](docs/数据来源说明.txt)

## 许可证

本项目仅供学习和参考使用。

## 联系方式

如有问题，请联系项目维护者。
