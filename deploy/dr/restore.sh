#!/usr/bin/env bash
# Production restore. Destructive by design; requires an explicit operator gate.
set -euo pipefail

DR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../cd/lib.sh
source "$DR_DIR/../cd/lib.sh"
# shellcheck source=lib-dr.sh
source "$DR_DIR/lib-dr.sh"

backup_dir="${1:-}"
[ "${ALLOW_PRODUCTION_RESTORE:-0}" = 1 ] || {
    warn "恢复会覆盖在线 PostgreSQL/MySQL。确认维护窗口后设 ALLOW_PRODUCTION_RESTORE=1"
    exit 64
}
[ -n "$backup_dir" ] && [ -f "$backup_dir/database.dump" ] && [ -f "$backup_dir/mysql.sql" ] || {
    warn "用法: ALLOW_PRODUCTION_RESTORE=1 bash deploy/dr/restore.sh <backup-dir>"
    exit 64
}

cd_load_env production
dr_assert_postgres_up
dr_assert_mysql_up

# Verify hashes and both dump formats before stopping any application service.
bash "$DR_DIR/backup.sh" --verify "$backup_dir"

log "停止入口和业务写入服务"
cd_compose stop nginx frontend backend mcp java-erp

log "恢复 PostgreSQL"
cd_compose exec -T "$DR_POSTGRES_SERVICE" pg_restore \
    --clean --if-exists --exit-on-error --no-owner --no-acl \
    -d "$DATABASE_URL" < "$backup_dir/database.dump"

log "恢复 MySQL"
cd_compose exec -T "$DR_MYSQL_SERVICE" sh -c '
    case "$MYSQL_DATABASE" in
      ""|*[!A-Za-z0-9_]*) echo "unsafe MYSQL_DATABASE" >&2; exit 64 ;;
    esac
    mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --execute \
      "DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`; CREATE DATABASE \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
'
cd_compose exec -T "$DR_MYSQL_SERVICE" sh -c \
    'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4' \
    < "$backup_dir/mysql.sql"

log "启动 Java ERP 并等待 Flyway/readiness"
cd_compose up -d --no-build java-erp
deadline=$((SECONDS + 180))
while [ "$SECONDS" -lt "$deadline" ]; do
    state="$(cd_compose ps --format '{{.Service}} {{.Health}}' java-erp 2>/dev/null || true)"
    [ "$state" = 'java-erp healthy' ] && break
    sleep 3
done
[ "${state:-}" = 'java-erp healthy' ] || {
    cd_compose logs --tail=200 java-erp >&2 || true
    die "Java ERP/Flyway 恢复后未 ready"
}

log "按 MCP → backend/frontend → nginx 顺序恢复服务"
cd_compose up -d --no-build mcp
cd_compose up -d --no-build backend frontend
cd_compose up -d --no-build nginx
cd_wait_healthy 300
cd_smoke

info "恢复完成：$backup_dir"
