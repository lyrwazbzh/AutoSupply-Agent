#!/usr/bin/env bash
# PostgreSQL 前向迁移、幂等和账本保护门禁。
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-ci.sh"

MIGRATE="$CI_REPO_ROOT/deploy/dr/migrate.sh"
SOURCE="$CI_REPO_ROOT/migrations/postgres"
WORK="${CI_MIGRATE_WORK:-/tmp/erp-migrate-e2e}"

ci_log "确认 PostgreSQL 正在运行"
ci_compose up -d --no-build postgres
ci_wait_healthy 120 || ci_die "PostgreSQL 没有就绪"

ci_log "执行 PostgreSQL 迁移"
bash "$MIGRATE" --dir "$SOURCE"
FIRST_COUNT="$(ci_compose exec -T postgres sh -c \
    'psql "$DATABASE_URL" -X -qAt -c "SELECT count(*) FROM app.schema_migrations"')"
[ "${FIRST_COUNT:-0}" -gt 0 ] || ci_die "迁移账本为空"

ci_log "重复执行必须幂等"
bash "$MIGRATE" --dir "$SOURCE"
SECOND_COUNT="$(ci_compose exec -T postgres sh -c \
    'psql "$DATABASE_URL" -X -qAt -c "SELECT count(*) FROM app.schema_migrations"')"
[ "$FIRST_COUNT" = "$SECOND_COUNT" ] || ci_die "重复迁移新增了账本记录"

ci_log "检查 pgvector、中文检索配置和写审计表"
CHECK="$(ci_compose exec -T postgres sh -c \
    'psql "$DATABASE_URL" -X -qAt <<"SQL"
SELECT
    (SELECT count(*) FROM pg_extension WHERE extname IN ($$vector$$, $$zhparser$$)),
    to_regconfig($$public.procurement_zh$$) IS NOT NULL,
    to_regclass($$audit.write_operations$$) IS NOT NULL;
SQL')"
[ "$CHECK" = "2|t|t" ] || ci_die "PostgreSQL 扩展或应用结构不完整：$CHECK"

rm -rf -- "$WORK"
mkdir -p "$WORK/changed" "$WORK/duplicate"
cp "$SOURCE"/*.sql "$WORK/changed/"
printf '\n-- changed after apply\n' >> "$WORK/changed/0001_unified.sql"
ci_log "已应用迁移内容被修改时必须停止"
if bash "$MIGRATE" --dir "$WORK/changed"; then
    ci_die "checksum 被修改的迁移仍然通过"
fi

cp "$SOURCE"/*.sql "$WORK/duplicate/"
printf 'SELECT 1;\n' > "$WORK/duplicate/0003_a.sql"
printf 'SELECT 1;\n' > "$WORK/duplicate/0003_b.sql"
ci_log "重复迁移编号必须停止"
if bash "$MIGRATE" --dir "$WORK/duplicate"; then
    ci_die "重复迁移编号仍然通过"
fi

ci_info "PostgreSQL 迁移、幂等与账本保护通过"
