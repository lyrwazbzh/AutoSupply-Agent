#!/usr/bin/env bash
# stack-smoke job 的断言脚本：在**完整**拓扑上起一套栈（含 privileged 的真 dind），
# 验证 compose 文件本身没被改坏、沙箱链路真的通。
#
#   bash deploy/ci/prepare-stack.sh
#   bash deploy/ci/stack-smoke.sh
#
# 与 smoke-edge.sh 的分工：
#   - smoke-edge.sh 换掉 dind/loader 两个服务，跑得快，管**认证与代理链路**；
#   - 本脚本一个服务都不换，管**拓扑本身**：起栈顺序、dind 与沙箱镜像灌入、
#     预热池真的建出容器。它是唯一验证 docker-compose.yml 的地方。
#
# 只在 ubuntu-latest 上跑：GitHub 托管的 runner 是一次性真 VM，privileged 在这里
# 安全且可用。自托管 runner 装在生产机上，**绝不能**让 PR 触发的 workflow 跑到
# 它上面（见 deploy/ci/lint-workflows.sh）。
set -euo pipefail

CI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/ci/lib-ci.sh
. "$CI_DIR/lib-ci.sh"

CRED_FILE="$CI_REPO_ROOT/deploy/ci/.ci-credentials.sh"
[ -f "$CRED_FILE" ] || ci_die "找不到 $CRED_FILE —— 先跑 bash deploy/ci/prepare-stack.sh"
# shellcheck source=/dev/null
. "$CRED_FILE"

BASE="${CI_BASE_URL:-http://127.0.0.1}"
FAILED=0
# 与 auth-path 不同：**不设 CI_OVERRIDE**，跑的就是 docker-compose.yml 原样。

# ---------------------------------------------------------------- 构建
# 这里故意让 compose 自己 build（不预建、不带 GHA 层缓存）：这个 job 的职责就是
# 验证 docker-compose.yml 的 build 配置本身（context、build args、共享镜像
# erp-agent-app:local 被 mcp 与 backend 复用）。慢几分钟是它的成本，不是缺陷。
#
# 两个 registry 参数必须**显式覆盖**：Dockerfile 里的默认值是国内源
# （PIP_INDEX_URL 阿里云、NPM_REGISTRY npmmirror），那是给国内部署机用的；
# runner 在境外，npmmirror 会直接 404 ——
#   npm error 404 'electron-to-chromium@https://registry.npmmirror.com/...' is not in this registry
# 注意 404 的是 npmmirror 自己的 tarball 路径，看起来像"包不存在"，实际是
# 镜像站对境外 IP 的行为，很容易误判成依赖问题。
#
# 传 --build-arg 不算削弱这个 job：compose 的 args 挂点被真的用上，反而多验了一条。
ci_log "构建镜像（compose 自己的 build 配置，registry 走官方源）"
ci_build \
    --build-arg NPM_REGISTRY=https://registry.npmjs.org/ \
    --build-arg PIP_INDEX_URL=https://pypi.org/simple/

# ---------------------------------------------------------------- 起栈
ci_log "起栈（完整拓扑，真 dind）"
ci_up
if ! ci_wait_healthy 600; then
    ci_dump
    exit 1
fi

# 空库由 Flyway 创建结构，测试数据由独立夹具显式写入，不开启 dev Seeder。
# 脚本使用与 backend/MCP 相同的 data 网络访问 java-erp，同时验证
# 查询、幂等建单、入出库与 operation 回查契约。
ci_log "Java ERP/Flyway 核心契约冒烟"
docker run --rm \
    --network "${CI_PROJECT}_data" \
    -v "$CI_REPO_ROOT/java_erp/scripts:/smoke:ro" \
    --entrypoint python \
    erp-agent-app:local \
    /smoke/smoke_harness.py \
    --base-url http://java-erp:8080 \
    --username "$CI_ADMIN_USER" \
    --password "$CI_ADMIN_PASSWORD" \
    --bootstrap-fixture

ci_log "Redis 查询缓存、登录限流与最近/常用冒烟"
docker run --rm \
    --network "${CI_PROJECT}_data" \
    -v "$CI_REPO_ROOT/java_erp/scripts:/smoke:ro" \
    --entrypoint python \
    erp-agent-app:local \
    /smoke/smoke_redis.py \
    --base-url http://java-erp:8080 \
    --username "$CI_ADMIN_USER" \
    --password "$CI_ADMIN_PASSWORD"

REDIS_PING="$(ci_compose exec -T redis sh -c \
    'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" ping')"
[ "$REDIS_PING" = "PONG" ] || ci_die "Redis 密码连接失败: $REDIS_PING"
PART_CACHE_KEYS="$(ci_compose exec -T redis sh -c \
    'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" --scan --pattern "erp:cache:v1:part-*"')"
SUPPLIER_CACHE_KEYS="$(ci_compose exec -T redis sh -c \
    'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" --scan --pattern "erp:cache:v1:supplier-*"')"
ACTIVITY_KEYS="$(ci_compose exec -T redis sh -c \
    'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" --scan --pattern "erp:activity:v1:*"')"
INVENTORY_KEYS="$(ci_compose exec -T redis sh -c \
    'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" --scan --pattern "inv:*"')"
[ -n "$PART_CACHE_KEYS" ] || ci_die "零件查询未产生 Redis 缓存"
[ -n "$SUPPLIER_CACHE_KEYS" ] || ci_die "供应商查询未产生 Redis 缓存"
[ -n "$ACTIVITY_KEYS" ] || ci_die "详情访问未产生 Redis activity ZSet"
[ -z "$INVENTORY_KEYS" ] || ci_die "库存路径错误地产生了 Redis Key: $INVENTORY_KEYS"

JAVA_ERP_CID="$(ci_compose ps -q java-erp)"
JAVA_ERP_USER="$(docker inspect -f '{{.Config.User}}' "$JAVA_ERP_CID")"
case "$JAVA_ERP_USER" in
    ''|root|0) ci_die "Java ERP 镜像以特权用户运行: ${JAVA_ERP_USER:-<empty>}" ;;
    *) ci_info "ok    Java ERP 非 root 用户: $JAVA_ERP_USER" ;;
esac

# ---------------------------------------------------------------- 一次性服务
# sandbox-image-loader 把 python:3.11-slim 预先灌进 dind。它必须是 exit 0 ——
# 非 0 意味着 dind 拉不到沙箱基础镜像，而首请求时的表现会是"沙箱创建超时"，
# 离根因很远。backend 的 depends_on 就是 service_completed_successfully，
# 所以它失败时 backend 根本不会起来；这条断言是为了把原因直接打出来。
LOADER="$(ci_compose ps --all --format '{{.Service}} {{.State}} {{.ExitCode}}' \
    | grep '^sandbox-image-loader' || true)"
ci_info "sandbox-image-loader：${LOADER:-（没找到这个服务？）}"
if printf '%s' "$LOADER" | grep -qE ' exited 0$'; then
    ci_info "ok    sandbox-image-loader 成功退出（沙箱基础镜像已灌进 dind）"
else
    ci_warn "FAIL  sandbox-image-loader 不是 exited 0 —— 看 ci_dump 里的日志"
    FAILED=$((FAILED + 1))
fi

# ---------------------------------------------------------------- 沙箱链路
# 七服务都 healthy 只说明进程活着；这条才说明**沙箱链路真的通**：
# backend → dind(2375) → 建出预热容器。它是 compose 拓扑 + 宿主内核 +
# dind 参数（overlay2 / mtu / ip_forward）合起来才成立的东西。
ci_log "等待 backend 建出预热容器（最长 240s）"
WARM=""
for _ in $(seq 1 48); do
    if ci_compose logs backend 2>/dev/null | grep -q 'Warm pool container created'; then
        WARM="$(ci_compose logs backend 2>/dev/null \
            | grep 'Warm pool container created' | tail -1)"
        break
    fi
    sleep 5
done
if [ -n "$WARM" ]; then
    ci_info "ok    ${WARM#*] }"
else
    ci_warn "FAIL  backend 日志里没有 'Warm pool container created' —— 全栈起来了但沙箱链路没通"
    ci_warn "      注意：这条路是优雅降级的（预热失败不阻止 Web 服务启动），"
    ci_warn "      所以健康检查全绿**也可能**是坏的，只有这条断言抓得住。"
    FAILED=$((FAILED + 1))
fi

# 顺便钉一条最外层的链路，让失败时能一眼看出是"整个栈没起来"还是"只有沙箱没通"。
ci_log "最外层探活"
CODE="$(ci_http_code "$BASE/healthz")"
if [ "$CODE" = "200" ]; then
    ci_info "ok    GET /healthz → 200"
else
    ci_warn "FAIL  GET /healthz → $CODE"
    FAILED=$((FAILED + 1))
fi

# Readiness 必须反映数据库连接：MySQL 不可用时不得继续接收流量，
# MySQL 恢复后必须自动回到 UP。放在所有业务冒烟之后，避免故意断库干扰用例。
ci_log "Readiness 数据库断开/恢复验证"
ci_compose stop mysql >/dev/null
READINESS_FAILED=0
for _ in $(seq 1 30); do
    if ! ci_compose exec -T java-erp curl -fsS \
        http://127.0.0.1:8080/actuator/health/readiness >/dev/null 2>&1; then
        READINESS_FAILED=1
        break
    fi
    sleep 2
done
[ "$READINESS_FAILED" = 1 ] || ci_die "MySQL 停止后 Java ERP readiness 仍为 UP"
ci_compose up -d --no-build mysql >/dev/null
ci_wait_healthy 180 || ci_die "MySQL 恢复后 Java ERP readiness 未恢复"

ci_log "Readiness Redis 断开/恢复验证"
ci_compose stop redis >/dev/null
REDIS_READINESS_FAILED=0
for _ in $(seq 1 30); do
    if ! ci_compose exec -T java-erp curl -fsS \
        http://127.0.0.1:8080/actuator/health/readiness >/dev/null 2>&1; then
        REDIS_READINESS_FAILED=1
        break
    fi
    sleep 2
done
[ "$REDIS_READINESS_FAILED" = 1 ] || ci_die "Redis 停止后 Java ERP readiness 仍为 UP"
ci_compose up -d --no-build redis >/dev/null
ci_wait_healthy 180 || ci_die "Redis 恢复后 Java ERP readiness 未恢复"

if [ "$FAILED" -eq 0 ]; then
    ci_log "全栈冒烟全部通过"
    exit 0
fi
ci_dump
ci_die "$FAILED 条断言失败" 1
