# PostgreSQL 备份、迁移与恢复

本目录是生产数据库运维的唯一入口。数据库权威状态统一保存在 PostgreSQL，
不再使用 MongoDB 备份、恢复或迁移链路。

| 文件 | 作用 |
|---|---|
| `lib-dr.sh` | PostgreSQL 容器检查、`psql`、`pg_dump`、dump 校验等公共原语 |
| `backup.sh` | 生成 custom-format dump、SHA-256 清单并执行保留策略 |
| `restore-drill.sh` | 把备份恢复到一次性 PostgreSQL，检查应用表和写审计表 |
| `migrate.sh` | 顺序执行 `migrations/postgres/*.sql`，维护 checksum 账本 |
| `offsite.sh` | 将备份目录复制到异地存储 |

## 数据范围

一次 `pg_dump` 覆盖同一个 PostgreSQL 数据库中的：

- LangGraph checkpoint 与 store；
- `app` 下的会话、展示消息、沙箱映射等应用数据；
- `audit.write_operations` 写操作审计；
- `knowledge` 业务知识；
- pgvector 字段、全文检索结构和迁移账本。

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

# 应用 PostgreSQL 迁移
bash deploy/dr/migrate.sh --dir migrations/postgres

# 查看待执行迁移
bash deploy/dr/migrate.sh --dir migrations/postgres --status
```

## 不变式

- 已应用迁移不得修改；修正必须新增迁移编号。
- `app.schema_migrations` 记录 migration id 与 SHA-256，checksum 不一致立即停止。
- 备份完成必须通过 `pg_restore --list` 和清单哈希校验。
- 恢复演练只在一次性 PostgreSQL 容器中执行，不覆盖在线数据库。
- 发布前备份失败时终止发布，不能把未校验 dump 当作可恢复备份。

PR 门禁对应脚本位于 `deploy/ci/backup-dr.sh` 和 `deploy/ci/migrate-e2e.sh`。
