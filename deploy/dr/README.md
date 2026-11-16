# PostgreSQL + MySQL 备份、迁移与恢复

本目录是生产数据库备份运维的统一入口。PostgreSQL 保存 Agent 会话、审计与知识，
MySQL 保存 Java ERP 业务数据；两者必须在同一个备份批次中生成并校验。

| 文件 | 作用 |
|---|---|
| `lib-dr.sh` | PostgreSQL/MySQL 容器检查、dump 和结构校验公共原语 |
| `backup.sh` | 生成 `database.dump` + `mysql.sql`、SHA-256 清单并执行保留策略 |
| `restore-drill.sh` | 恢复到一次性 PostgreSQL/MySQL，检查应用表、审计表和库存不变式 |
| `restore.sh` | 维护窗口内覆盖恢复生产两库，按 Java ERP/Flyway → MCP → Backend 顺序起栈 |
| `migrate.sh` | 顺序执行 `migrations/postgres/*.sql`，维护 checksum 账本 |
| `offsite.sh` | 将备份目录复制到异地存储 |

## 数据范围

一个备份目录同时包含：

- LangGraph checkpoint 与 store；
- `app` 下的会话、展示消息、沙箱映射等应用数据；
- `audit.write_operations` 写操作审计；
- `knowledge` 业务知识；
- pgvector 字段、全文检索结构和迁移账本。
- Java ERP 的用户、供应商、零件、订单、库存、物流与幂等/operation 记录。

用户下载文件属于 `download-data` 卷，不包含在数据库 dump 中，应由对象存储或独立卷
备份策略管理。`dind-data` 是可重建的沙箱运行数据，不作为权威业务备份。

## 常用命令

```bash
# 创建并校验备份
bash deploy/dr/backup.sh --no-offsite

# 查看备份
bash deploy/dr/backup.sh --list

# 校验指定备份
bash deploy/dr/backup.sh --verify /var/backups/erp-agent/<backup>

# 隔离恢复演练
bash deploy/dr/restore-drill.sh /var/backups/erp-agent/<backup>

# 生产恢复（覆盖在线两库，必须先完成变更审批和维护窗口）
ALLOW_PRODUCTION_RESTORE=1 bash deploy/dr/restore.sh /var/backups/erp-agent/<backup>

# 应用 PostgreSQL 迁移
bash deploy/dr/migrate.sh --dir migrations/postgres

# 查看待执行迁移
bash deploy/dr/migrate.sh --dir migrations/postgres --status
```

## 不变式

- 已应用迁移不得修改；修正必须新增迁移编号。
- `app.schema_migrations` 记录 migration id 与 SHA-256，checksum 不一致立即停止。
- 备份完成必须通过 `pg_restore --list`、MySQL dump 完整性和两个文件的清单哈希校验。
- 恢复演练只在一次性 PostgreSQL/MySQL 容器中执行，不覆盖在线数据库。
- 发布前备份失败时终止发布，不能把未校验 dump 当作可恢复备份。

PR 门禁对应脚本位于 `deploy/ci/backup-dr.sh` 和 `deploy/ci/migrate-e2e.sh`。
