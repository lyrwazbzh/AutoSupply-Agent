#!/usr/bin/env bash
# 从统一入口验证登录、JWT 转发、RBAC 与账号变更即时失效。
set -euo pipefail

CI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/ci/lib-ci.sh
. "$CI_DIR/lib-ci.sh"

CI_OVERRIDE="deploy/ci/compose.ci.yml"
CRED_FILE="$CI_REPO_ROOT/deploy/ci/.ci-credentials.sh"
[ -f "$CRED_FILE" ] || ci_die "找不到 $CRED_FILE —— 先跑 prepare-stack.sh"
# shellcheck source=/dev/null
. "$CRED_FILE"

BASE="${CI_BASE_URL:-http://127.0.0.1}"
FAILED=0
check_code() {
    local desc="$1" expect="$2" actual="$3"
    if [ "$expect" = "$actual" ]; then ci_info "ok    $desc → $actual"
    else ci_warn "FAIL  $desc → 期望 $expect，实际 $actual"; FAILED=$((FAILED + 1)); fi
}
json_field() {
    python -c 'import json,sys; d=json.load(sys.stdin); print(d["data"]'"$1"')'
}

ci_log "起栈（统一身份 + Java ERP RBAC）"
ci_up
if ! ci_wait_healthy 420; then ci_dump; exit 1; fi

check_code "GET /healthz" 200 "$(ci_http_code "$BASE/healthz")"
check_code "GET / 登录页公开" 200 "$(ci_http_code "$BASE/")"
check_code "GET /api/history 无令牌" 401 "$(ci_http_code "$BASE/api/history")"
check_code "GET ERP dashboard 无令牌" 401 "$(ci_http_code "$BASE/api/erp/statistics/dashboard")"

ci_log "管理员登录与跨服务令牌转发"
LOGIN="$(curl -fsS --max-time 20 -H 'Content-Type: application/json' \
    -d "{\"username\":\"$CI_ADMIN_USER\",\"password\":\"$CI_ADMIN_PASSWORD\"}" \
    "$BASE/api/auth/login")"
ADMIN_TOKEN="$(printf '%s' "$LOGIN" | json_field '["accessToken"]')"
[ -n "$ADMIN_TOKEN" ] || ci_die "登录响应没有 accessToken"
AUTH=(-H "Authorization: Bearer $ADMIN_TOKEN")
check_code "GET /api/auth/me" 200 "$(ci_http_code "${AUTH[@]}" "$BASE/api/auth/me")"
check_code "GET Python history" 200 "$(ci_http_code "${AUTH[@]}" "$BASE/api/history")"
check_code "GET Java ERP dashboard" 200 "$(ci_http_code "${AUTH[@]}" "$BASE/api/erp/statistics/dashboard")"
check_code "伪造 Bearer 被拒绝" 401 "$(ci_http_code -H 'Authorization: Bearer forged' "$BASE/api/history")"

ci_log "VIEWER 角色矩阵与账号状态即时生效"
VIEWER_PASSWORD='ViewerOnly!123'
CREATE="$(curl -fsS --max-time 20 "${AUTH[@]}" -H 'Content-Type: application/json' \
    -d "{\"username\":\"ci-viewer\",\"displayName\":\"CI Viewer\",\"password\":\"$VIEWER_PASSWORD\",\"roles\":[\"VIEWER\"]}" \
    "$BASE/api/erp/admin/users")"
VIEWER_ID="$(printf '%s' "$CREATE" | json_field '["id"]')"
VIEWER_LOGIN="$(curl -fsS --max-time 20 -H 'Content-Type: application/json' \
    -d "{\"username\":\"ci-viewer\",\"password\":\"$VIEWER_PASSWORD\"}" \
    "$BASE/api/auth/login")"
VIEWER_TOKEN="$(printf '%s' "$VIEWER_LOGIN" | json_field '["accessToken"]')"
VIEWER_AUTH=(-H "Authorization: Bearer $VIEWER_TOKEN")
check_code "VIEWER 可读 dashboard" 200 "$(ci_http_code "${VIEWER_AUTH[@]}" "$BASE/api/erp/statistics/dashboard")"
check_code "VIEWER 不可管理用户" 403 "$(ci_http_code "${VIEWER_AUTH[@]}" "$BASE/api/erp/admin/users")"
check_code "VIEWER 可用助手历史" 200 "$(ci_http_code "${VIEWER_AUTH[@]}" "$BASE/api/history")"

curl -fsS --max-time 20 "${AUTH[@]}" -H 'Content-Type: application/json' \
    -X PATCH -d '{"status":2}' "$BASE/api/erp/admin/users/$VIEWER_ID/status" >/dev/null
check_code "停用后旧令牌立即失效（Python active check）" 401 \
    "$(ci_http_code "${VIEWER_AUTH[@]}" "$BASE/api/history")"
check_code "停用后旧令牌立即失效（Java active filter）" 401 \
    "$(ci_http_code "${VIEWER_AUTH[@]}" "$BASE/api/erp/statistics/dashboard")"

ci_log "绕过 nginx 直连 backend 仍必须携带有效 JWT"
NET="$(docker network ls --format '{{.Name}}' | grep -x "${CI_PROJECT}_edge" | head -1 || true)"
[ -n "$NET" ] || ci_die "找不到网络 ${CI_PROJECT}_edge"
DIRECT="$(docker run --rm --network "$NET" --entrypoint python erp-agent-app:local -c '
import urllib.request, urllib.error
try:
    print(urllib.request.urlopen("http://backend:8000/api/history", timeout=10).status)
except urllib.error.HTTPError as exc:
    print(exc.code)
' 2>/dev/null || true)"
check_code "直连 backend 无令牌" 401 "$DIRECT"

if [ "$FAILED" -eq 0 ]; then ci_log "统一身份 edge 冒烟全部通过"; exit 0; fi
ci_dump
ci_die "$FAILED 条断言失败" 1
