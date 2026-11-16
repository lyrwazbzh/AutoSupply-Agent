#!/usr/bin/env bash
# Safe host-MySQL -> Compose-MySQL migration helper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE=(docker compose -f "$REPO_ROOT/docker-compose.yml")
ENV_FILE="$REPO_ROOT/deploy/.env"

SOURCE_MYSQL_HOST="${SOURCE_MYSQL_HOST:-127.0.0.1}"
SOURCE_MYSQL_PORT="${SOURCE_MYSQL_PORT:-3306}"
SOURCE_MYSQL_USER="${SOURCE_MYSQL_USER:-root}"
SOURCE_MYSQL_PASSWORD="${SOURCE_MYSQL_PASSWORD:-}"
MYSQL_DATABASE="${MYSQL_DATABASE:-motorparts_db}"
MIGRATION_DIR="${MIGRATION_DIR:-$REPO_ROOT/.migration/mysql}"
BASE_TABLES=(user supplier part purchase_order order_detail inventory logistics)
ALL_TABLES=("${BASE_TABLES[@]}" erp_operation order_idempotency)

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: migrate-host.sh <preflight|export|import|verify>

Required environment for source operations:
  SOURCE_MYSQL_HOST, SOURCE_MYSQL_PORT, SOURCE_MYSQL_USER,
  SOURCE_MYSQL_PASSWORD, MYSQL_DATABASE

Optional:
  MIGRATION_DIR             output directory (default .migration/mysql)
  ALLOW_MYSQL_IMPORT=1      required for import
  ALLOW_NONEMPTY_TARGET=1   permit import into a non-empty Compose database

Recommended sequence:
  preflight -> stop old Java ERP writes -> export -> import -> verify
EOF
}

require_source_tools() {
    command -v mysql >/dev/null || die "mysql client is required"
    command -v mysqldump >/dev/null || die "mysqldump is required"
    [ -n "$SOURCE_MYSQL_PASSWORD" ] || die "SOURCE_MYSQL_PASSWORD is required"
}

source_mysql() {
    MYSQL_PWD="$SOURCE_MYSQL_PASSWORD" mysql \
        --host="$SOURCE_MYSQL_HOST" --port="$SOURCE_MYSQL_PORT" \
        --user="$SOURCE_MYSQL_USER" --database="$MYSQL_DATABASE" \
        --batch --skip-column-names "$@"
}

source_query() { source_mysql --execute "$1"; }

target_query() {
    local sql="$1"
    "${COMPOSE[@]}" exec -T mysql sh -c \
        'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" --batch --skip-column-names --execute "$1"' \
        -- "$sql"
}

source_table_exists() {
    [ "$(source_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='$1';")" = 1 ]
}

target_table_exists() {
    [ "$(target_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='$1';")" = 1 ]
}

write_source_metrics() {
    local output="$1" table rows range
    : > "$output"
    for table in "${ALL_TABLES[@]}"; do
        if source_table_exists "$table"; then
            rows="$(source_query "SELECT COUNT(*) FROM \`$table\`;")"
            if [ "$table" = erp_operation ] || [ "$table" = order_idempotency ]; then
                range="-|-"
            else
                range="$(source_query "SELECT COALESCE(MIN(id),0), COALESCE(MAX(id),0) FROM \`$table\`;")"
                range="${range//$'\t'/|}"
            fi
            printf '%s\t%s\t%s\n' "$table" "$rows" "$range" >> "$output"
        fi
    done
    printf 'ORDER_TOTAL\t%s\t-\n' "$(source_query 'SELECT COALESCE(SUM(total_amount),0) FROM purchase_order;')" >> "$output"
    printf 'INVENTORY_TOTAL\t%s\t-\n' "$(source_query 'SELECT COALESCE(SUM(current_quantity),0) FROM inventory;')" >> "$output"
}

write_target_metrics() {
    local output="$1" table rows range
    : > "$output"
    for table in "${ALL_TABLES[@]}"; do
        if target_table_exists "$table"; then
            rows="$(target_query "SELECT COUNT(*) FROM \`$table\`;")"
            if [ "$table" = erp_operation ] || [ "$table" = order_idempotency ]; then
                range="-|-"
            else
                range="$(target_query "SELECT COALESCE(MIN(id),0), COALESCE(MAX(id),0) FROM \`$table\`;")"
                range="${range//$'\t'/|}"
            fi
            printf '%s\t%s\t%s\n' "$table" "$rows" "$range" >> "$output"
        fi
    done
    printf 'ORDER_TOTAL\t%s\t-\n' "$(target_query 'SELECT COALESCE(SUM(total_amount),0) FROM purchase_order;')" >> "$output"
    printf 'INVENTORY_TOTAL\t%s\t-\n' "$(target_query 'SELECT COALESCE(SUM(current_quantity),0) FROM inventory;')" >> "$output"
}

preflight() {
    require_source_tools
    log "Checking required source tables"
    local table failures=0 count
    for table in "${BASE_TABLES[@]}"; do
        if ! source_table_exists "$table"; then
            printf 'missing table: %s\n' "$table" >&2
            failures=$((failures + 1))
        fi
    done
    [ "$failures" -eq 0 ] || die "$failures required tables are missing"

    log "Checking unique natural keys, orphan details and inventory invariants"
    while IFS=$'\t' read -r label count; do
        [ "${count:-0}" = 0 ] || die "$label has $count violations"
    done < <(source_query "
      SELECT 'duplicate supplier_code', COUNT(*) FROM (SELECT supplier_code FROM supplier GROUP BY supplier_code HAVING COUNT(*)>1) x
      UNION ALL SELECT 'duplicate part_code', COUNT(*) FROM (SELECT part_code FROM part GROUP BY part_code HAVING COUNT(*)>1) x
      UNION ALL SELECT 'duplicate order_number', COUNT(*) FROM (SELECT order_number FROM purchase_order GROUP BY order_number HAVING COUNT(*)>1) x
      UNION ALL SELECT 'orphan order_detail order', COUNT(*) FROM order_detail d LEFT JOIN purchase_order o ON o.id=d.order_id WHERE o.id IS NULL
      UNION ALL SELECT 'orphan order_detail part', COUNT(*) FROM order_detail d LEFT JOIN part p ON p.id=d.part_id WHERE p.id IS NULL
      UNION ALL SELECT 'negative inventory', COUNT(*) FROM inventory WHERE current_quantity < 0;")

    mkdir -p "$MIGRATION_DIR"
    write_source_metrics "$MIGRATION_DIR/source-metrics.tsv"
    log "Preflight passed; metrics: $MIGRATION_DIR/source-metrics.tsv"
}

export_source() {
    require_source_tools
    preflight
    mkdir -p "$MIGRATION_DIR"
    local partial="$MIGRATION_DIR/motorparts.sql.partial"
    local dump="$MIGRATION_DIR/motorparts.sql"
    rm -f -- "$partial"
    log "Creating a consistent source snapshot"
    MYSQL_PWD="$SOURCE_MYSQL_PASSWORD" mysqldump \
        --host="$SOURCE_MYSQL_HOST" --port="$SOURCE_MYSQL_PORT" \
        --user="$SOURCE_MYSQL_USER" \
        --single-transaction --quick --routines --triggers --events \
        --hex-blob --default-character-set=utf8mb4 --set-gtid-purged=OFF \
        --no-tablespaces --databases "$MYSQL_DATABASE" > "$partial"
    grep -q '^-- Dump completed on ' "$partial" || die "mysqldump did not complete"
    mv "$partial" "$dump"
    sha256sum "$dump" > "$dump.sha256"
    log "Export complete: $dump"
}

wait_mysql() {
    local i
    for i in $(seq 1 90); do
        if "${COMPOSE[@]}" exec -T mysql sh -c \
            'mysqladmin ping -h 127.0.0.1 -uroot -p"$MYSQL_ROOT_PASSWORD" --silent' \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    die "Compose MySQL did not become healthy"
}

import_target() {
    [ "${ALLOW_MYSQL_IMPORT:-0}" = 1 ] || die "set ALLOW_MYSQL_IMPORT=1 after the maintenance window starts"
    [ -f "$ENV_FILE" ] || die "missing $ENV_FILE; create it from deploy/.env.example"
    local dump="$MIGRATION_DIR/motorparts.sql"
    [ -f "$dump" ] && [ -f "$dump.sha256" ] || die "missing dump/checksum in $MIGRATION_DIR"
    (cd "$MIGRATION_DIR" && sha256sum -c motorparts.sql.sha256)

    log "Starting only Compose MySQL"
    "${COMPOSE[@]}" up -d mysql
    wait_mysql
    local target_tables
    target_tables="$(target_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE();")"
    if [ "$target_tables" -gt 0 ] && [ "${ALLOW_NONEMPTY_TARGET:-0}" != 1 ]; then
        die "target database already has $target_tables tables; use a fresh mysql-data volume or set ALLOW_NONEMPTY_TARGET=1"
    fi

    log "Importing source snapshot into Compose MySQL"
    "${COMPOSE[@]}" exec -T mysql sh -c \
        'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4' < "$dump"

    log "Starting Java ERP so Flyway can baseline and migrate"
    "${COMPOSE[@]}" up -d java-erp
    local i status
    for i in $(seq 1 120); do
        status="$("${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}}' java-erp 2>/dev/null || true)"
        [ "$status" = 'java-erp healthy' ] && return 0
        sleep 2
    done
    "${COMPOSE[@]}" logs --tail=200 java-erp >&2 || true
    die "Java ERP/Flyway did not become ready"
}

verify_target() {
    [ -f "$MIGRATION_DIR/source-metrics.tsv" ] || die "source metrics are missing"
    wait_mysql
    write_target_metrics "$MIGRATION_DIR/target-metrics.tsv"

    log "Comparing source rows, key ranges and business aggregates"
    local name expected expected_range actual actual_range
    while IFS=$'\t' read -r name expected expected_range; do
        actual="$(awk -F '\t' -v name="$name" '$1==name {print $2}' "$MIGRATION_DIR/target-metrics.tsv")"
        actual_range="$(awk -F '\t' -v name="$name" '$1==name {print $3}' "$MIGRATION_DIR/target-metrics.tsv")"
        [ "$actual" = "$expected" ] || die "$name mismatch: source=$expected target=${actual:-missing}"
        [ "$actual_range" = "$expected_range" ] || die "$name key range mismatch: source=$expected_range target=${actual_range:-missing}"
    done < "$MIGRATION_DIR/source-metrics.tsv"

    [ "$(target_query 'SELECT COUNT(*) FROM order_detail d LEFT JOIN purchase_order o ON o.id=d.order_id LEFT JOIN part p ON p.id=d.part_id WHERE o.id IS NULL OR p.id IS NULL;')" = 0 ] \
        || die "target has orphan order details"
    [ "$(target_query 'SELECT COUNT(*) FROM inventory WHERE current_quantity < 0;')" = 0 ] \
        || die "target has negative inventory"
    [ "$(target_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('erp_operation','order_idempotency','order_expiry_task','flyway_schema_history');")" = 4 ] \
        || die "Flyway/governance tables are incomplete"
    log "Target verification passed. Keep the source database read-only during the observation window."
}

case "${1:-}" in
    preflight) preflight ;;
    export) export_source ;;
    import) import_target ;;
    verify) verify_target ;;
    *) usage; exit 64 ;;
esac
