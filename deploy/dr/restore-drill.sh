#!/usr/bin/env bash
# Restore PostgreSQL and MySQL backups into isolated disposable servers.
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
[ -n "$backup_dir" ] && [ -f "$backup_dir/database.dump" ] && [ -f "$backup_dir/mysql.sql" ] || {
    warn "没有可演练的 PostgreSQL + MySQL 备份"
    exit 1
}

dr_assert_postgres_up
dr_verify_dump "$backup_dir/database.dump"
dr_verify_mysql_dump "$backup_dir/mysql.sql"

name="erp-pg-restore-$RANDOM-$$"
mysql_name="erp-mysql-restore-$RANDOM-$$"
password="$(openssl rand -hex 16)"
cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker rm -f "$mysql_name" >/dev/null 2>&1 || true
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

mysql_image="${CD_MYSQL_IMAGE:-mysql:8.0.40}"
docker run -d --name "$mysql_name" --memory 768m --cpus 1 \
    -e MYSQL_ROOT_PASSWORD="$password" "$mysql_image" >/dev/null

for _ in $(seq 1 90); do
    docker exec "$mysql_name" mysqladmin ping -h 127.0.0.1 -uroot -p"$password" --silent \
        >/dev/null 2>&1 && break
    sleep 1
done
docker exec "$mysql_name" mysqladmin ping -h 127.0.0.1 -uroot -p"$password" --silent >/dev/null
docker exec -i "$mysql_name" mysql -uroot -p"$password" < "$backup_dir/mysql.sql"

mysql_tables="$(docker exec "$mysql_name" mysql -uroot -p"$password" -Nse \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('information_schema','mysql','performance_schema','sys');")"
[ "${mysql_tables:-0}" -gt 0 ] || { warn "MySQL 恢复后没有业务表"; exit 1; }

mysql_db="$(sed -n 's/^USE `\([^`]*\)`;/\1/p' "$backup_dir/mysql.sql" | head -1)"
case "$mysql_db" in
    ''|*[!A-Za-z0-9_]*) warn "MySQL dump 中的数据库名不安全: $mysql_db"; exit 1 ;;
esac
has_inventory="$(docker exec "$mysql_name" mysql -uroot -p"$password" -Nse \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$mysql_db' AND table_name='inventory';")"
negative_inventory=0
if [ "$has_inventory" -gt 0 ]; then
    negative_inventory="$(docker exec "$mysql_name" mysql -uroot -p"$password" -Nse \
        "SELECT COUNT(*) FROM \`$mysql_db\`.inventory WHERE current_quantity < 0;")"
fi
[ "${negative_inventory:-0}" = 0 ] || { warn "MySQL 恢复后存在负库存"; exit 1; }

info "PostgreSQL + MySQL 恢复演练通过: $backup_dir（PG 表 $tables，MySQL 表 $mysql_tables）"
