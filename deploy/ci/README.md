# deploy/ci

这里保存 PR 门禁和集成栈脚本。数据库门禁已经统一为 PostgreSQL。

| 文件 | 作用 |
|---|---|
| `prepare-stack.sh` | 生成 PostgreSQL 口令、`DATABASE_URL`、nginx 共享密钥和 CI 凭据 |
| `backup-dr.sh` | 启动 PostgreSQL，执行迁移、真实备份、校验、隔离恢复和负向用例 |
| `migrate-e2e.sh` | 验证迁移、幂等、pgvector/zhparser、checksum 与重复编号保护 |
| `dr-logic-test.sh` | PostgreSQL DR 脚本的无 Docker 静态门禁 |
| `migrate-logic-test.sh` | PostgreSQL 迁移器的无 Docker 静态门禁 |
| `smoke-edge.sh` | 验证认证与 nginx → backend → PostgreSQL 链路 |
| `stack-smoke.sh` | 验证完整 Compose 拓扑及真实 dind 沙箱链路 |
| `patrol-logic-test.sh` | 验证巡检状态指纹与变化通知逻辑 |

## 两类集成栈

| | `auth-path` | `stack-smoke` |
|---|---|---|
| 数据库 | 真实 PostgreSQL | 真实 PostgreSQL |
| ERP/MCP/backend/frontend/nginx | 真实服务 | 真实服务 |
| dind | Alpine 替身 | 真实 privileged dind |
| 目标 | 认证、代理、内部共享密钥 | Compose 拓扑、沙箱镜像和预热池 |

## 数据库门禁

`backup-dr` job 使用和生产相同的 `deploy/postgres` 镜像及 `deploy/dr` 脚本：

1. 构建并启动 PostgreSQL；
2. 执行 `migrations/postgres`；
3. 写入固定种子；
4. 使用 `pg_dump --format=custom` 创建备份；
5. 使用 `pg_restore --list` 校验结构；
6. 恢复到一次性 PostgreSQL 并检查应用表；
7. 篡改清单，确认损坏备份会被拒绝；
8. 重复执行迁移并验证账本不会增长；
9. 修改已应用迁移或制造重复编号，确认迁移器停止。

## 本地执行

```bash
bash deploy/ci/prepare-stack.sh
bash deploy/ci/dr-logic-test.sh
bash deploy/ci/migrate-logic-test.sh
bash deploy/ci/backup-dr.sh
bash deploy/ci/migrate-e2e.sh
```

`prepare-stack.sh` 默认拒绝覆盖非 CI 生成的 `deploy/.env`。确需本机运行时先备份真实
密钥，再显式设置 `CI_FORCE=1`。
