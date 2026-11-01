#!/usr/bin/env bash
# PostgreSQL disaster-recovery primitives shared by backup/migrate/offsite.

DR_POSTGRES_SERVICE="${CD_POSTGRES_SERVICE:-postgres}"

dr_assert_postgres_up() {
    local cid state
    # deploy.sh 已经加载环境；独立执行 backup/migrate/CI 时在这里补齐 compose 上下文。
    [ -n "${PROJECT:-}" ] || cd_load_env production
    cid="$(cd_compose ps -q "$DR_POSTGRES_SERVICE" 2>/dev/null | head -1 || true)"
    [ -n "$cid" ] || { warn "compose 里没有运行中的 $DR_POSTGRES_SERVICE"; return 1; }
    state="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || true)"
    [ "$state" = running ] || { warn "PostgreSQL 容器状态是 $state"; return 1; }
}

dr_psql() {
    local sql="$1"
    cd_compose exec -T "$DR_POSTGRES_SERVICE" sh -c \
        'psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -X -qAt -c "$1"' -- "$sql"
}

dr_pg_dump() {
    cd_compose exec -T "$DR_POSTGRES_SERVICE" sh -c \
        'pg_dump "$DATABASE_URL" --format=custom --compress=6 --no-owner --no-acl'
}

dr_verify_dump() {
    local dump="$1"
    [ -s "$dump" ] || { warn "备份文件为空: $dump"; return 1; }
    cd_compose exec -T "$DR_POSTGRES_SERVICE" pg_restore --list < "$dump" >/dev/null
}

dr_offsite_mark() {
    local dir="$1" result="$2" message="${3:-}"
    {
        printf 'RESULT=%s\n' "$result"
        printf 'AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'MESSAGE=%s\n' "$message"
    } > "$dir/offsite.status"
}
