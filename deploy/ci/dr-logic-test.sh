#!/usr/bin/env bash
# PostgreSQL DR 脚本的无 Docker 静态门禁。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="$ROOT/deploy/dr/lib-dr.sh"
BACKUP="$ROOT/deploy/dr/backup.sh"
RESTORE="$ROOT/deploy/dr/restore-drill.sh"

bash -n "$LIB" "$BACKUP" "$RESTORE"
grep -q 'pg_dump' "$LIB"
grep -q 'pg_restore --list' "$LIB"
grep -q 'FORMAT=postgres-custom' "$BACKUP"
grep -q 'audit.write_operations' "$RESTORE"
if grep -Eqi 'mongo(db|dump|restore|sh)?' "$LIB" "$BACKUP" "$RESTORE"; then
    printf 'DR 主链仍包含 MongoDB 命令\n' >&2
    exit 1
fi
printf 'PostgreSQL DR 静态门禁通过\n'
