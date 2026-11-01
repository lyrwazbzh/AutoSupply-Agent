#!/usr/bin/env bash
# Restore the newest PostgreSQL backup into an isolated disposable server.
set -euo pipefail

DR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../cd/lib.sh
source "$DR_DIR/../cd/lib.sh"
# shellcheck source=lib-dr.sh
source "$DR_DIR/lib-dr.sh"

backup_dir="${1:-}"
if [ -z "$backup_dir" ]; then
    backup_dir="$(find "$CD_BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d \
        -name '20*T*Z-*' -print 2>/dev/null | sort -r | head -1)"
fi
[ -n "$backup_dir" ] && [ -f "$backup_dir/database.dump" ] || {
    warn "没有可演练的 PostgreSQL 备份"
    exit 1
}

dr_assert_postgres_up
dr_verify_dump "$backup_dir/database.dump"

name="erp-pg-restore-$RANDOM-$$"
password="$(openssl rand -hex 16)"
cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

image="${CD_POSTGRES_IMAGE:-erp-agent-postgres:local}"
docker run -d --name "$name" --memory 768m --cpus 1 \
    -e POSTGRES_PASSWORD="$password" "$image" >/dev/null

for _ in $(seq 1 60); do
    docker exec "$name" pg_isready -U postgres >/dev/null 2>&1 && break
    sleep 1
done
docker exec "$name" pg_isready -U postgres >/dev/null

docker exec -i "$name" pg_restore --exit-on-error --no-owner --no-acl \
    -U postgres -d postgres < "$backup_dir/database.dump"

tables="$(docker exec "$name" psql -U postgres -d postgres -qAt -c \
    "SELECT count(*) FROM pg_tables WHERE schemaname IN ('app','audit','knowledge');")"
[ "${tables:-0}" -gt 0 ] || { warn "恢复后没有应用表"; exit 1; }

audit_table="$(docker exec "$name" psql -U postgres -d postgres -qAt -c \
    "SELECT to_regclass('audit.write_operations') IS NOT NULL;")"
[ "$audit_table" = t ] || { warn "恢复后缺少 audit.write_operations"; exit 1; }

info "PostgreSQL 恢复演练通过: $backup_dir（应用表 $tables）"
