#!/usr/bin/env bash
# 为 CI 集成 job 生成一套可运行的本地配置。幂等：重复跑会重新生成一份新口令。
#
#   bash deploy/ci/prepare-stack.sh
#
# 生成运行配置、JWT 密钥、一份凭据和占位证书（均被忽略，永不入库）：
#   deploy/.env                    随机 PostgreSQL/MySQL/Redis 口令与一次性 ERP 管理员
#   deploy/nginx.env               从模板派生的 TLS 开关
#   deploy/secrets/erp-jwt-*.pem   Java 签名私钥与服务验签公钥
#   deploy/ci/.ci-credentials.sh   冒烟登录凭据
#   deploy/nginx/tls/{cert,key}.pem  自签 TLS 占位证书。CI 走纯 HTTP（nginx.env 里
#                                  TLS_ENABLED= 空），但 nginx.conf 的 :443 server
#                                  **无条件**加载该路径，缺了它 nginx master 加载配置
#                                  就 emerg、容器永远 restarting —— 两个集成 job 都会
#                                  卡在等 healthy 超时。与 deploy/cd 的占位证书同契约。
#
# 为什么用随机值而不是写死：写死的话"两处不一致时应该 401"这类断言就退化成
# "常量等于常量"，永远绿。随机值让每次运行都是一次真实的一致性验证。
#
# 本机误用的防呆见下面 CI_MARKER 那段 —— 这个名字的脚本会覆盖真实的 deploy/.env。
set -euo pipefail

# 从第一行就收紧权限：下面每个文件里都有口令或密钥，不要出现"先 644 再 chmod"
# 的窗口（生产机上就踩过 644 世界可读这个坑）。
umask 077

CI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/ci/lib-ci.sh
. "$CI_DIR/lib-ci.sh"
REPO="$CI_REPO_ROOT"
cd "$REPO"

ENV_FILE="deploy/.env"
ENV_EXAMPLE="deploy/.env.example"
NGINX_ENV_FILE="deploy/nginx.env"
NGINX_ENV_EXAMPLE="deploy/nginx.env.example"
CRED_FILE="deploy/ci/.ci-credentials.sh"

# 写在生成文件第一行的标记。它的唯一作用是让下面的防呆能区分「这是脚本生成的」
# 和「这是人配的真实配置」—— deploy/.env 里有真实的 CHATANYWHERE_API_KEY，
# 误覆盖一次的代价是有人要去找回自己的 Key。
CI_MARKER="# GENERATED-BY: deploy/ci/prepare-stack.sh（CI 专用，可随时重建）"

info() { ci_info "$*"; }
die()  { ci_die "$1"; }

# ---------------------------------------------------------------- 防呆
# 目标文件已存在、且不是本脚本生成的 → 拒绝。本机要跑必须显式 CI_FORCE=1，
# 且会先备份成 *.bak.<时间戳>。
guard_existing() {
    local f="$1"
    [ -f "$f" ] || return 0
    grep -qF "$CI_MARKER" "$f" && return 0
    if [ "${CI_FORCE:-}" != "1" ]; then
        die "$f 已存在且不是 CI 生成的 —— 里面可能是你的真实配置。
    真要覆盖：先自己备份，然后 CI_FORCE=1 bash deploy/ci/prepare-stack.sh
    （脚本会再存一份 $f.bak.<时间戳>）"
    fi
    local bak="$f.bak.$(date +%Y%m%dT%H%M%S)"
    cp -p "$f" "$bak"
    printf '\033[33m !! 已备份原文件到 %s\033[0m\n' "$bak" >&2
}

set_var() { ci_set_var "$@"; }

# 从模板派生：先写标记头，再照抄模板正文（模板第一行可能是注释，无妨）。
derive_from() {
    local src="$1" dst="$2"
    [ -f "$src" ] || die "找不到模板 $src"
    { printf '%s\n' "$CI_MARKER"; cat "$src"; } > "$dst"
}

# ---------------------------------------------------------------- 生成
for f in "$ENV_FILE" "$NGINX_ENV_FILE"; do guard_existing "$f"; done
POSTGRES_PASS="$(openssl rand -hex 16)"
MYSQL_PASS="$(openssl rand -hex 16)"
MYSQL_ROOT_PASS="$(openssl rand -hex 16)"
REDIS_PASS="$(openssl rand -hex 16)"
ADMIN_USER="ci-admin"
ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"

# Java ERP 持有签名私钥；backend/mcp 只挂载公钥。runner 是一次性环境，
# 每次 job 生成全新密钥可以同时验证密钥挂载没有漏配。
bash deploy/generate-jwt-keys.sh

derive_from "$ENV_EXAMPLE" "$ENV_FILE"
set_var "$ENV_FILE" POSTGRES_USER erp_agent
set_var "$ENV_FILE" POSTGRES_PASSWORD "$POSTGRES_PASS"
set_var "$ENV_FILE" POSTGRES_DB erp_agent
set_var "$ENV_FILE" DATABASE_URL \
    "postgresql://erp_agent:${POSTGRES_PASS}@postgres:5432/erp_agent"
set_var "$ENV_FILE" MYSQL_DATABASE motorparts_db
set_var "$ENV_FILE" MYSQL_USER motorparts
set_var "$ENV_FILE" MYSQL_PASSWORD "$MYSQL_PASS"
set_var "$ENV_FILE" MYSQL_ROOT_PASSWORD "$MYSQL_ROOT_PASS"
set_var "$ENV_FILE" REDIS_PASSWORD "$REDIS_PASS"
set_var "$ENV_FILE" REDIS_HOST redis
set_var "$ENV_FILE" REDIS_PORT 6379
set_var "$ENV_FILE" ERP_DB_HOST mysql
set_var "$ENV_FILE" ERP_DB_PORT 3306
set_var "$ENV_FILE" ERP_BOOTSTRAP_ADMIN_USERNAME "$ADMIN_USER"
set_var "$ENV_FILE" ERP_BOOTSTRAP_ADMIN_PASSWORD "$ADMIN_PASSWORD"
set_var "$ENV_FILE" ERP_COOKIE_SECURE false
# 假 Key，但形态要像真的：backend 的 lifespan 不构造模型，所以这里不会被用到。
# 用 sk-dummy 前缀是为了命中 .gitleaks.toml 的 allowlist（虽然 .env 被 gitignore、
# 不会进历史，但本地 detect --no-git 扫目录时不该报一条假阳性）。
set_var "$ENV_FILE" CHATANYWHERE_API_KEY "sk-dummy-ci-not-a-real-key"
set_var "$ENV_FILE" PUBLIC_BASE_URL "http://127.0.0.1"
set_var "$ENV_FILE" CORS_ALLOW_ORIGINS "http://127.0.0.1"
derive_from "$NGINX_ENV_EXAMPLE" "$NGINX_ENV_FILE"

cat > "$CRED_FILE" <<EOF
# GENERATED-BY: deploy/ci/prepare-stack.sh —— 一次性 CI 口令，不要提交。
# 本文件已在 .gitignore 与 deploy/cd/leak-check.sh 的 SECRET_PATHS 里。
export HTTP_PORT=80
CI_BASE_URL='http://127.0.0.1'
CI_ADMIN_USER='$ADMIN_USER'
CI_ADMIN_PASSWORD='$ADMIN_PASSWORD'
EOF

# 生产机那次教训：密钥文件曾是 644 世界可读。runner 是一次性的，但保持同样的
# 习惯不花任何代价。
chmod 600 "$ENV_FILE" "$NGINX_ENV_FILE" "$CRED_FILE"

# ---------------------------------------------------------------- nginx TLS 占位证书
# nginx.conf 的 :443 server **无条件**写了 ssl_certificate /etc/nginx/tls/cert.pem：
# 该指令在 master 加载配置期就解析路径，跟 TLS_ENABLED 开关是不是空无关。CI 这里是
# 纯 HTTP（上面 nginx.env 里 TLS_ENABLED= 空），又不跑 bootstrap.sh / deploy.sh，
# 没人生成证书 —— 不补这一份，nginx 一启动就 emerg（cannot load certificate
# ".../tls/cert.pem": No such file or directory），容器一直 restarting，smoke-edge
# 等 420s、stack-smoke 等 600s 双双超时，而且认证 / 沙箱断言一条都跑不到。
#
# 用**同一条** openssl（RSA2048 / 3650 天 / CN=localhost），与
# deploy/cd/lib.sh 的 cd_ensure_nginx_tls_cert 保持一个契约，别在这里发散。
# compose 以**目录**挂 ./deploy/nginx/tls:/etc/nginx/tls:ro，无单文件挂载的 inode 坑。
TLS_DIR="$REPO/deploy/nginx/tls"
mkdir -p "$TLS_DIR"
if [ ! -s "$TLS_DIR/cert.pem" ] || [ ! -s "$TLS_DIR/key.pem" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -keyout "$TLS_DIR/key.pem" -out "$TLS_DIR/cert.pem" \
        -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost" >/dev/null 2>&1 \
        || ci_die "自签 nginx TLS 占位证书失败（openssl req -x509）"
fi
# 证书由 master(root) 加载期读取（worker 不自行 open），600 即可，与 cd 那份占位一致。
chmod 600 "$TLS_DIR/cert.pem" "$TLS_DIR/key.pem"

info "$ENV_FILE / $NGINX_ENV_FILE / JWT 密钥已生成（另有 $TLS_DIR 占位证书）"
info "一次性 ERP 管理员：$ADMIN_USER（口令仅保存在 $CRED_FILE）"
