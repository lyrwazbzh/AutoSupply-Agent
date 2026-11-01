#!/usr/bin/env bash
# PostgreSQL 备份、校验、隔离恢复与保留策略门禁。
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-ci.sh"

WORK="${CI_BACKUP_WORK:-/tmp/erp-backup-dr}"
BACKUP_ROOT="$WORK/backups"
DR_BACKUP="$CI_REPO_ROOT/deploy/dr/backup.sh"
DR_RESTORE="$CI_REPO_ROOT/deploy/dr/restore-drill.sh"

cleanup() {
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        ci_dump "$WORK/diagnostics" || true
    fi
}
trap cleanup EXIT

rm -rf -- "$WORK"
mkdir -p "$BACKUP_ROOT"

ci_log "构建并启动 PostgreSQL"
ci_compose build postgres
ci_compose up -d --no-build postgres
ci_wait_healthy 240 || ci_die "PostgreSQL 没在 240s 内 healthy"

ci_log "应用 PostgreSQL 结构迁移"
bash "$CI_REPO_ROOT/deploy/dr/migrate.sh" \
    --dir "$CI_REPO_ROOT/migrations/postgres"

ci_log "写入可校验的种子数据"
ci_compose exec -T postgres sh -c \
    'psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -X <<"SQL"
CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE IF NOT EXISTS app.ci_backup_seed (
    id integer PRIMARY KEY,
    value text NOT NULL
);
TRUNCATE app.ci_backup_seed;
INSERT INTO app.ci_backup_seed VALUES (1, $$alpha$$), (2, $$beta$$);
SQL'

ci_log "执行真实 pg_dump 并校验 pg_restore 清单"
CD_BACKUP_DIR="$BACKUP_ROOT" CD_BACKUP_VERSION=ci \
    bash "$DR_BACKUP" --no-offsite
LATEST="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z-*' \
    -print | sort -r | head -1)"
[ -n "$LATEST" ] || ci_die "没有生成 PostgreSQL 备份"
CD_BACKUP_DIR="$BACKUP_ROOT" bash "$DR_BACKUP" --verify "$LATEST"

ci_log "恢复到一次性 PostgreSQL 并检查应用表"
CD_BACKUP_DIR="$BACKUP_ROOT" bash "$DR_RESTORE" "$LATEST"

ci_log "负向用例：损坏校验和必须失败"
cp "$LATEST/manifest.txt" "$LATEST/manifest.txt.clean"
sed -i 's/^DATABASE_SHA256=.*/DATABASE_SHA256=deadbeef/' "$LATEST/manifest.txt"
if CD_BACKUP_DIR="$BACKUP_ROOT" bash "$DR_BACKUP" --verify "$LATEST"; then
    ci_die "损坏的 PostgreSQL 备份被错误判定为有效"
fi
mv "$LATEST/manifest.txt.clean" "$LATEST/manifest.txt"

ci_log "保留策略只留下最新两份"
for day in 01 02 03; do
    mkdir -p "$BACKUP_ROOT/202601${day}T000000Z-old"
done
CD_BACKUP_DIR="$BACKUP_ROOT" CD_BACKUP_KEEP=2 bash "$DR_BACKUP" --prune
COUNT="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z-*' | wc -l | tr -d ' ')"
[ "$COUNT" = 2 ] || ci_die "PostgreSQL 备份保留策略异常：期望 2，实际 $COUNT"

ci_info "PostgreSQL 备份、恢复、负向校验与保留策略通过"
