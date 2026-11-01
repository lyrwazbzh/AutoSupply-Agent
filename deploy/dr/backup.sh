#!/usr/bin/env bash
# PostgreSQL custom-format backup with structural verification and retention.
set -euo pipefail

DR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../cd/lib.sh
source "$DR_DIR/../cd/lib.sh"
# shellcheck source=lib-dr.sh
source "$DR_DIR/lib-dr.sh"

NO_OFFSITE=0
MODE=backup
VERIFY_DIR=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --no-offsite) NO_OFFSITE=1 ;;
        --prune) MODE=prune ;;
        --list) MODE=list ;;
        --verify) MODE=verify; VERIFY_DIR="${2:-}"; shift ;;
        *) warn "未知参数: $1"; exit 1 ;;
    esac
    shift
done

dr_prune_pg_backups() {
    local keep="${CD_BACKUP_KEEP:-7}" item count=0
    [ -d "$CD_BACKUP_DIR" ] || return 0
    while IFS= read -r item; do
        count=$((count + 1))
        if [ "$count" -gt "$keep" ]; then
            rm -rf -- "$item"
            info "已剪枝旧备份: $item"
        fi
    done < <(find "$CD_BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d \
        -name '20*T*Z-*' -print | sort -r)
}

dr_verify_pg_backup() {
    local dir="$1" dump="$dir/database.dump" expected actual
    [ -f "$dir/manifest.txt" ] || { warn "缺少 manifest.txt: $dir"; return 1; }
    expected="$(sed -n 's/^DATABASE_SHA256=//p' "$dir/manifest.txt")"
    actual="$(sha256sum "$dump" | awk '{print $1}')"
    [ -n "$expected" ] && [ "$expected" = "$actual" ] || {
        warn "database.dump 校验和不一致"
        return 1
    }
    dr_verify_dump "$dump"
}

case "$MODE" in
    list)
        find "$CD_BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | sort -r
        exit 0
        ;;
    prune)
        dr_prune_pg_backups
        exit 0
        ;;
    verify)
        [ -n "$VERIFY_DIR" ] || { warn "--verify 需要备份目录"; exit 1; }
        dr_assert_postgres_up
        dr_verify_pg_backup "$VERIFY_DIR"
        exit 0
        ;;
esac

dr_assert_postgres_up
mkdir -p "$CD_BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
version="${CD_BACKUP_VERSION:-manual}"
safe_version="$(printf '%s' "$version" | tr -c 'A-Za-z0-9._-' '_')"
final_dir="$CD_BACKUP_DIR/${stamp}-${safe_version}"
[ ! -e "$final_dir" ] || final_dir="${final_dir}-$$"
work_dir="${final_dir}.partial.$$"
mkdir -p "$work_dir"
cleanup_partial() {
    [ -z "${work_dir:-}" ] || rm -rf -- "$work_dir"
}
trap cleanup_partial EXIT

info "导出 PostgreSQL: $work_dir/database.dump"
dr_pg_dump > "$work_dir/database.dump"
dr_verify_dump "$work_dir/database.dump"
checksum="$(sha256sum "$work_dir/database.dump" | awk '{print $1}')"

{
    printf 'FORMAT=postgres-custom\n'
    printf 'CREATED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'VERSION=%s\n' "$version"
    printf 'GIT_SHA=%s\n' "${CD_BACKUP_GIT_SHA:-}"
    printf 'DATABASE_SHA256=%s\n' "$checksum"
} > "$work_dir/manifest.txt"

mv "$work_dir" "$final_dir"
work_dir=""
dr_verify_pg_backup "$final_dir"

if [ "$NO_OFFSITE" = 0 ] && [ -x "$DR_DIR/offsite.sh" ]; then
    bash "$DR_DIR/offsite.sh" "$final_dir"
else
    dr_offsite_mark "$final_dir" skipped "--no-offsite"
fi

dr_prune_pg_backups

if [ -n "${BACKUP_RESULT_FILE:-}" ]; then
    {
        printf 'DB_DUMP=%s\n' "$final_dir/database.dump"
        printf 'DB_DUMP_SHA256=%s\n' "$checksum"
    } > "$BACKUP_RESULT_FILE"
fi

trap - EXIT
info "PostgreSQL 备份完成并通过 pg_restore 清单校验: $final_dir"
