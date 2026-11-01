#!/usr/bin/env bash
# PostgreSQL 迁移器的无 Docker 静态门禁。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MIGRATE="$ROOT/deploy/dr/migrate.sh"
MIGRATIONS="$ROOT/migrations/postgres"

bash -n "$MIGRATE"
compgen -G "$MIGRATIONS/[0-9][0-9][0-9][0-9]_*.sql" >/dev/null
grep -q 'app.schema_migrations' "$MIGRATE"
grep -q 'checksum' "$MIGRATE"
grep -q '迁移编号重复' "$MIGRATE"
if grep -Eqi 'mongo(db|sh)?|\.js' "$MIGRATE"; then
    printf '迁移主链仍包含 MongoDB 逻辑\n' >&2
    exit 1
fi
printf 'PostgreSQL 迁移静态门禁通过\n'
