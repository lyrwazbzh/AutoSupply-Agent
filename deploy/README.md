# 部署说明

> 在一台**全新的云主机**上从零部署（装 Docker、配镜像加速、建 swap、生成
> `deploy/.env` 与登录账号、构建、起服务、等 healthy）用
> [cloud/README.md](cloud/README.md) 的一键脚本，不用照着手工敲。
> 本文档讲的是栈本身怎么工作、怎么运维、出问题怎么查。

## 架构

```
浏览器 :80/443 ──登录/JWT──▶ nginx
   │
 nginx ──/api/auth/、/api/erp/──→ java-erp:8080
   │    ──/api/chat/、/api/─────→ backend:8000
   └────/───────────→ frontend:3000
                          │
 backend ──→ postgres:5432 / mcp:9000 / java-erp:8080 ──→ mysql:3306
                                      └───────────────→ redis:6379
    │                       ▲
    └──DOCKER_HOST──→ dind:2375 ──→ erp-sandbox-* 容器
                                    └── mcp-sandbox 网络 ──→ mcp:9000
```

沙箱走 `docker:dind` sidecar，而不是挂宿主机的 `/var/run/docker.sock`。好处是沙箱容器被圈在 dind 自己的镜像/容器存储里，删掉 `dind-data` 卷就等于清空所有沙箱，也不在宿主机上留下任何容器。

**但这不等于安全隔离**：backend 能驱动 daemon API，而 dind 是 `privileged`，逃逸到宿主机 root 的路径依然存在（与挂 socket 同级）。只应部署在受控网络里。

## 快速开始

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env：至少填 LLM/对外地址，并替换 MySQL 与 Redis 占位口令
cp deploy/nginx.env.example deploy/nginx.env
# 生成 RS256 密钥，并配置一次性初始管理员（脚本会打印随机密码）
bash deploy/init-security.sh

docker compose up -d --build
docker compose ps          # 等所有服务变成 healthy
```

浏览器打开 `http://<服务器地址>/`，使用 ERP 初始管理员登录。登录后请修改密码，
并清空 `deploy/.env` 中两个 `ERP_BOOTSTRAP_ADMIN_*` 值。

`PUBLIC_BASE_URL` 必须是浏览器能打开的地址（如 `http://192.168.1.50`），它决定 Agent 生成的下载链接指向哪里。填 `localhost` 的话用户点链接会指向自己的机器。

### 统一身份与权限

Java ERP 是唯一身份源和令牌签发方：密码只保存自适应哈希，登录成功后签发短期
RS256 access token，并用 HttpOnly、SameSite=Strict Cookie 轮换 refresh token。
同一枚 access token 由 Java ERP、Python Backend 与 MCP 分别验证受众和签名；私钥
只挂载到 `java-erp`，其余服务只读公钥。

账号停用、角色或权限变更会提高 `authz_version` 并撤销刷新会话。Java 请求逐次检查
数据库状态，Python 入口向 Java ERP 做 active check，因此旧 token 会立即失效。
内置角色为 `ADMIN`、`PURCHASER`、`WAREHOUSE`、`VIEWER`；接口权限均使用明确的
permission code，不使用通配管理员权限。

## 前置条件

- Docker Engine 24+ / Compose v2
- 宿主机文件系统 `ext4` 或 `xfs`（`xfs` 需要 `ftype=1`：`xfs_info / | grep ftype`）
- 出网：`api.deepseek.com`（LLM）+ 镜像仓库（dind 要拉 `python:3.11-slim`）
- 至少 4GB 可用内存（每个沙箱容器 `mem_limit=512m` + 预热池）

## 日常运维

> 正式发布/回滚走 `deploy/cd/`（`deploy.sh` / `build.sh` / `status.sh`），由
> GitHub Actions 经人工审批调起，见 **[deploy/cd/README.md](cd/README.md)** 与
> **[deploy/runner/README.md](runner/README.md)**。下面的手工命令适合本机调试，
> **不要**用来给生产换版 —— 手工 `up` 会让状态文件与实际运行的镜像脱节，
> `status.sh` 会报不一致。

```bash
docker compose logs -f backend          # 应用日志
docker compose restart backend          # 改完 src/skills 后必须重启（见下）
docker compose exec dind docker ps      # 看沙箱容器

# 查看生成的下载文件
docker run --rm -v erp-agent_download-data:/d alpine ls -l /d
```

### 备份

**不要手工拼装数据库备份命令。** 使用 [deploy/dr/](dr/README.md) 的 PostgreSQL
与 MySQL 一致性备份、校验和恢复链路：

```bash
bash deploy/dr/backup.sh          # pg_dump → 清单校验 → 剪枝 → 外推
bash deploy/dr/backup.sh --list   # 看有哪些
```

`backup.sh` 同时执行 custom-format `pg_dump` 与 `mysqldump --single-transaction`，
写入 SHA-256 清单。恢复演练会把两份备份恢复到一次性数据库，并检查审计表、ERP
业务表和库存不变式。

`download-data` 卷中的用户报告不在 PostgreSQL dump 内，应使用对象存储或独立卷备份；
卷丢失后历史下载链接会失效。完整边界见 [deploy/dr/README.md](dr/README.md)。

`dind-data` 不需要备份：沙箱容器可以根据 PostgreSQL 中的租约状态重新分配和重建。

生产机上的定时备份与巡检由 systemd timer 负责（`deploy/monitor/`，装一次：
`sudo bash deploy/monitor/install-monitor.sh`），见同一份文档。

### 改了 `src/skills/` 之后

`src/skills` 是 bind mount，**镜像里那份被完全遮蔽**。改了仓库里的 skill 之后：

```bash
docker compose restart backend     # 让 SkillsSyncMiddleware 重新扫描
```

只 `docker compose up -d --build` 不生效——重建镜像不会改变挂载内容。

### 改了后端代码之后

```bash
docker compose up -d --build backend mcp
```

backend 和 mcp 共用同一个镜像（`erp-agent-app:local`），要一起重建。

## 已知限制

### 多副本边界

AgentSession 所有权、执行租约、用户沙箱分配与暖池归属已经外置到 PostgreSQL；
进程内 `_sessions` / `_entries` 只作为可重建缓存，同一用户的运行由带 TTL 的数据库
租约串行化。Backend 可以增加 worker/副本而不会覆盖 `sandbox_cache`。

生成文件仍在 Backend 本地临时目录，因此多副本入口要为 `/api/download/` 配置粘性
路由或共享 artifact 存储。共享 dind 仍是 SPOF，不等同于沙箱高可用。

### 认证的边界

- access token 默认 15 分钟，浏览器只保存在内存中；刷新依赖 HttpOnly Cookie。
- 会话历史和下载文件均绑定 JWT `sub`，客户端传入的 `user_id` 不作为身份来源。
- 助手写 ERP 同时需要 `assistant:erp-write` 与对应业务权限，审批入口另需
  `erp:order:approve`。
- 钉钉外部回调只使用开放平台 HMAC 签名，不接受浏览器 JWT；未配置密钥时默认拒绝。

### 沙箱内访问 MCP

阶段 2 默认关闭 `SANDBOX_MCP_URL` 与 `SANDBOX_MCP_HOST_IP`。不能把用户 access token
注入会执行模型生成代码且可出网的沙箱；Agent 主进程仍通过带 Bearer 的 MCP 客户端
访问 ERP。若以后恢复沙箱直连，应先增加短期、降权、不可转用的 capability proxy。

链路：

```
沙箱容器 ──/etc/hosts: mcp=172.31.0.10──▶ dind 网关 ──转发+MASQUERADE──▶ mcp:9000
```

为什么绕这么一圈：沙箱容器跑在 dind 自己的 bridge 网络里，既解析不了 compose 服务名（dind 的内嵌 DNS 不认识 `mcp`），也和 mcp 不在同一个二层网络。所以由 backend 把 mcp 在 `mcp-sandbox` 网络上的**静态 IP** 写进沙箱容器的 `/etc/hosts`。用静态 IP 而非每次解析，是为了让 mcp 重建换 IP 后沙箱里的地址依然有效。

`mcp-sandbox` 网络刻意只放 `mcp` 和 `dind`，**不能让 dind 挂到 `data` 上** —— 那样沙箱里模型生成的代码就能顺着 dind 的路由够到 `postgres:5432`（`internal: true` 只挡出网，不挡同宿主机上网络之间的转发）。

Agent 侧怎么知道能用：`src/agent/memory/AGENTS.md` 里让它先跑 `os.getenv("MCP_SERVER_URL")` 自己判断，为空就不要尝试。所以没配这条通路时，Agent 不会去撞墙。

上图只说明历史网络拓扑，不是重新开启该能力的操作指南。

### 其它

- `/workspace` 挂载带 `noexec`：Agent 生成的 `./script.sh` 和编译产物无法直接执行（`python x.py` 可以，因为被 exec 的是 `/usr/local/bin/python`）。这是既有行为。
- Mock ERP 仅保留在 CI 契约测试覆盖文件中，不进入默认 Compose 或发布产物。
- Java ERP 镜像以非 root 用户运行；其余容器仍需逐项收紧运行身份。

## 故障排查

**backend 起不来，日志里有 `falling back to LocalShell` 或 `ALLOW_LOCAL_SHELL_FALLBACK`**

这是设计行为。容器里设了 `ALLOW_LOCAL_SHELL_FALLBACK=false`，沙箱不可用时**直接失败**而不是退回本机执行——否则会在 backend 进程环境（含 `CHATANYWHERE_API_KEY`）里跑模型生成的代码。检查 `docker compose logs dind` 和 `docker compose exec dind docker info`。

**图表功能时好时坏**

容器化部署的沙箱镜像（`deploy/sandbox/Dockerfile`，tag 由 `SANDBOX_IMAGE` 决定）已预装 matplotlib/pandas/numpy，`chart_generator` 检测到可导入就直接用。若沙箱镜像退回了裸 `python:3.11-slim`（比如本地开发没构建预装镜像），才会运行时 `pip install`——这时确认 dind 能出网（或配置 PyPI 镜像源）。

**重启后 dind 里堆了一批 `erp-sandbox-warm-*`**

`prune_orphans()` 已在 backend 启动时清扫。如果仍在堆积，说明 dind API 在 backend 启动时不可用（日志里会有 `Orphan prune skipped`），重启 backend 即可。

**所有接口都返回 401，但明明登录了**

检查浏览器 `/api/auth/refresh` 是否携带 `erp_refresh` Cookie、Java ERP readiness、JWT
公钥是否正确挂载到 backend/MCP，以及三者的 issuer/audience 是否与 `deploy/.env` 一致。
账号状态或权限刚变化时旧 access token 返回 401 是预期行为，前端会回到登录页。

**日志里出现 `Ignoring client-supplied user_id`**

有客户端在试图指定别人的身份。正常情况下不该出现 —— 前端传的 `user-001` 会被覆盖，所以只在 AUTH_MODE 切换过程中或有人手工构造请求时看到。

**nginx 502**

`docker compose ps` 看所有服务是否 healthy。业务主链路的启动顺序是 MySQL/Redis healthy → Java ERP/Flyway ready → MCP healthy → backend/frontend → nginx；PostgreSQL 与 dind/沙箱链路按各自依赖并行启动。backend 的 `start_period` 是 90s（要建预热池）。

**沙箱里 `curl http://mcp:9000` 失败**

按顺序查：`deploy/.env` 的 `SANDBOX_MCP_URL`/`SANDBOX_MCP_HOST_IP` 是否都非空；`docker compose exec dind docker exec erp-sandbox-xxx cat /etc/hosts` 看有没有 `mcp` 那行；`docker compose exec dind ping -c1 172.31.0.10` 看 dind 自身能否够到 mcp。注意**已有的沙箱不会自动获得新配置**，改完要 `docker compose restart backend` 让它重建容器（或等 30 分钟空闲回收）。

**改了 `deploy/.env` 里的 PostgreSQL 账号密码但不生效**

`POSTGRES_USER`、`POSTGRES_PASSWORD` 和 `POSTGRES_DB` 只在数据卷**首次初始化**时生效。
生产环境应通过受控凭据轮换修改，不能直接执行 `docker compose down -v`，后者会删除全部数据。

MySQL 的 `MYSQL_*` 初始化变量也只在 `mysql-data` 卷首次初始化时生效。宿主机旧数据库的切换必须使用 [mysql/README.md](mysql/README.md) 的预检、快照、校验与回退流程，不要手工重建数据卷。

Redis 只加入内部 `data` 网络，不发布 6379。它只保存零件/供应商查询缓存、登录限流和按用户隔离的最近/常用记录；不保存库存、订单、HITL 或 Agent 记忆。修改 `REDIS_PASSWORD` 后必须重建 Redis 与 Java ERP 容器，使两端同时读取新口令。
