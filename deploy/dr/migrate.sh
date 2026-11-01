#!/usr/bin/env bash
# Forward-only PostgreSQL migration runner with checksum ledger.
set -euo pipefail

DR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../cd/lib.sh
source "$DR_DIR/../cd/lib.sh"
# shellcheck source=lib-dr.sh
source "$DR_DIR/lib-dr.sh"

SOURCE_DIR=""
SOURCE_SHA=""
MODE=apply
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dir) SOURCE_DIR="${2:-}"; shift ;;
        --sha) SOURCE_SHA="${2:-}"; shift ;;
        --status) MODE=status ;;
        --dry-run) MODE=dry-run ;;
        *) warn "未知参数: $1"; exit 1 ;;
    esac
    shift
done

tmp=""
cleanup() { [ -z "$tmp" ] || rm -rf -- "$tmp"; }
trap cleanup EXIT

if [ -n "$SOURCE_SHA" ]; then
    [[ "$SOURCE_SHA" =~ ^[0-9a-fA-F]{40}$ ]] || { warn "--sha 必须是 40 位 commit"; exit 1; }
    tmp="$(mktemp -d)"
    git --git-dir="$CD_IMAGE_REPO" archive "$SOURCE_SHA" migrations/postgres \
        | tar -x -C "$tmp"
    SOURCE_DIR="$tmp/migrations/postgres"
elif [ -z "$SOURCE_DIR" ]; then
    SOURCE_DIR="$CD_REPO_ROOT/migrations/postgres"
elif [ -d "$SOURCE_DIR/postgres" ]; then
    SOURCE_DIR="$SOURCE_DIR/postgres"
fi

[ -d "$SOURCE_DIR" ] || { warn "迁移目录不存在: $SOURCE_DIR"; exit 1; }
dr_assert_postgres_up

dr_psql "
CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE IF NOT EXISTS app.schema_migrations (
    migration_id text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    git_sha text
);"

shopt -s nullglob
files=("$SOURCE_DIR"/[0-9][0-9][0-9][0-9]_*.sql)
shopt -u nullglob

previous_id=""
for file in "${files[@]}"; do
    migration_id="$(basename "$file")"
    migration_id="${migration_id%%_*}"
    if [ "$migration_id" = "$previous_id" ]; then
        warn "迁移编号重复: $migration_id"
        exit 1
    fi
    previous_id="$migration_id"
done

for file in "${files[@]}"; do
    base="$(basename "$file")"
    migration_id="${base%%_*}"
    checksum="$(sha256sum "$file" | awk '{print $1}')"
    applied="$(dr_psql "SELECT checksum FROM app.schema_migrations WHERE migration_id = '$migration_id';")"
    if [ -n "$applied" ]; then
        [ "$applied" = "$checksum" ] || {
            warn "已应用迁移 $migration_id 的 checksum 被修改"
            exit 1
        }
        [ "$MODE" = status ] && info "$migration_id applied"
        continue
    fi

    if [ "$MODE" = status ] || [ "$MODE" = dry-run ]; then
        info "$migration_id pending ($base)"
        continue
    fi

    info "应用 PostgreSQL 迁移: $base"
    {
        printf 'BEGIN;\n'
        cat "$file"
        printf "\nINSERT INTO app.schema_migrations(migration_id, checksum, git_sha) VALUES ('%s', '%s', '%s');\n" \
            "$migration_id" "$checksum" "$SOURCE_SHA"
        printf 'COMMIT;\n'
    } | cd_compose exec -T "$DR_POSTGRES_SERVICE" sh -c \
        'psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -X'
done

[ "${#files[@]}" -gt 0 ] || info "没有 PostgreSQL 迁移文件"
