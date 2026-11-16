#!/usr/bin/env bash
# 为已有部署补齐阶段 2 的 JWT 配置与一次性管理员。不会覆盖已有密钥或口令。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
ENV_FILE=deploy/.env
[ -f "$ENV_FILE" ] || cp deploy/.env.example "$ENV_FILE"
umask 077

set_var() {
    local key="$1" value="$2"
    awk -v key="$key" -v val="$value" '
      BEGIN { done=0 }
      $0 ~ "^" key "=" { print key "=" val; done=1; next }
      { print }
      END { if (!done) print key "=" val }
    ' "$ENV_FILE" > "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
}
value_of() { sed -n "s/^$1=//p" "$ENV_FILE" | head -1; }

bash deploy/generate-jwt-keys.sh
set_var ERP_SECURITY_ENABLED true
set_var ERP_JWT_PRIVATE_KEY_PATH /run/secrets/erp-jwt-private.pem
set_var ERP_JWT_PUBLIC_KEY_PATH /run/secrets/erp-jwt-public.pem
set_var ERP_JWT_REQUIRE_CONFIGURED_KEY true
set_var ERP_JWT_ISSUER java-erp
set_var ERP_JWT_AUDIENCE erp-api,assistant-api,mcp
set_var AUTH_MODE jwt
set_var JWT_PUBLIC_KEY_PATH /run/secrets/erp-jwt-public.pem
set_var JWT_ISSUER java-erp
set_var JWT_AUDIENCE assistant-api
set_var MCP_AUTH_ENABLED true
set_var MCP_JWT_AUDIENCE mcp

ADMIN_USER="${ERP_ADMIN_USER:-$(value_of ERP_BOOTSTRAP_ADMIN_USERNAME)}"
ADMIN_PASSWORD="${ERP_ADMIN_PASSWORD:-$(value_of ERP_BOOTSTRAP_ADMIN_PASSWORD)}"
if [ -z "$ADMIN_USER" ]; then ADMIN_USER=admin; fi
if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"
    GENERATED_ADMIN=1
fi
set_var ERP_BOOTSTRAP_ADMIN_USERNAME "$ADMIN_USER"
set_var ERP_BOOTSTRAP_ADMIN_PASSWORD "$ADMIN_PASSWORD"
chmod 600 "$ENV_FILE"

echo "阶段 2 安全配置已就绪。管理员：$ADMIN_USER"
if [ -n "${GENERATED_ADMIN:-}" ]; then
    echo "一次性初始密码：$ADMIN_PASSWORD"
    echo "登录后请修改密码，并清空 deploy/.env 中两个 ERP_BOOTSTRAP_ADMIN_* 值。"
fi
