#!/usr/bin/env bash
# 生成 Java ERP RS256 签名密钥。私钥只挂载给 java-erp，Python 服务只读公钥。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_DIR="$REPO_ROOT/deploy/secrets"
PRIVATE_KEY="$SECRET_DIR/erp-jwt-private.pem"
PUBLIC_KEY="$SECRET_DIR/erp-jwt-public.pem"

umask 077
mkdir -p "$SECRET_DIR"

if [ -s "$PRIVATE_KEY" ] || [ -s "$PUBLIC_KEY" ]; then
    echo "JWT 密钥已存在；为避免令牌被意外全部失效，未覆盖。" >&2
    echo "如需轮换，请先备份并显式删除 deploy/secrets 下的旧密钥。" >&2
    exit 0
fi

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$PRIVATE_KEY"
openssl pkey -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY"
chmod 600 "$PRIVATE_KEY"
chmod 644 "$PUBLIC_KEY"
echo "已生成 $PRIVATE_KEY 与 $PUBLIC_KEY"
