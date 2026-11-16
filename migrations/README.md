# PostgreSQL 数据库结构

运行时只有一套数据库：PostgreSQL + pgvector。应用启动时由
`src/database.py` 幂等创建应用表，LangGraph 的 checkpoint/store 表
分别由 `PostgresSaver.setup()` 和 `PostgresStore.setup()` 创建。

`postgres/` 下的迁移按编号顺序执行。`0003` 约束 LangGraph 的 `store` 表，
因此必须在 `PostgresStore.setup()` 已创建该表后执行；应用启动路径会在 setup 后
通过 `setup_memory_search_schema()` 幂等应用同一约束。`0004` 增加独立审批队列、
跨实例运行租约、AgentSession 所有权和沙箱分配/暖池所有权。

```bash
for migration in migrations/postgres/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
done
```

新增结构时创建 `postgres/000N_description.sql`，遵循以下规则：

1. 只前进，不修改已发布迁移。
2. 使用事务和 `IF [NOT] EXISTS`，保证可安全重跑。
3. 先扩展、后收缩；部署新代码前不得破坏上一版代码所需字段。
4. 迁移只管理结构，批量业务回填使用独立的可断点任务。
5. LangGraph 自有表不复制进这里，由对应库的 `setup()` 管理。

写审计事件表是 append-only：数据库触发器会拒绝 `UPDATE` 和 `DELETE`。会话 UI
数据删除不会级联删除 `audit` schema 中的业务审计记录。
