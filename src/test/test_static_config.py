"""跨文件不变量：同一件事抄在几个地方，改一处忘了另一处。

这些断言**不启动 Docker、不连网络、不导入 src 里任何模块**（纯 stdlib 读文件 +
正则）。它们存在的理由是：`deploy/cd/README.md` 里那句"改静态 IP 要同步改两处"
以前只是文档，而文档不会拦住任何人 —— 现在由测试拦住。

具体钉住的四件事：

1. `SANDBOX_MCP_HOST_IP` 在三个文件里必须完全一致，且落在 `mcp-sandbox` 的
   子网内。改坏任意一处 → mcp 换了地址而沙箱容器的 /etc/hosts 还写着旧的 →
   沙箱内所有 MCP 工具挂掉，症状是超时（很难往配置上想）。
2. `deploy/nginx/nginx.conf` 只保留传输层职责，并让 HTTP/HTTPS 共用同一份代理路由。
3. 前端源码里不得有硬编码的后端绝对地址（镜像必须与环境无关）。
4. `tls.conf.template` 被 nginx.conf 在 http{} 顶层 include：开关必须用 map
   定义、不能用 set（set 在该上下文 nginx -t 直接 emerg，真机发布回滚过）。
   nginx worker 固定为非特权用户 `nginx`，nginx.env 必须显式带
   `TLS_ENABLED=` 空行。
   另：nginx.conf 的 :443 server 无条件加载 TLS 证书，纯 HTTP 场景路径上也得有占位 ——
   CI 集成栈不跑 bootstrap/deploy，由 deploy/ci/prepare-stack.sh 自签一份，否则两个
   集成 job 都会卡在等 nginx healthy 超时（smoke-edge 420s / stack-smoke 600s）。

第 2 条的运行时对照在 `deploy/ci/smoke-edge.sh`（集成 job）。这里只做**结构**
断言 —— 它能抓住"删了一行 header"，抓不住"proxy_pass 指到了错的端口"，后者
只有真起一套栈才发现。两者都要。
"""
import ipaddress
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ENV_EXAMPLE = REPO / "deploy" / ".env.example"
NGINX_ENV_EXAMPLE = REPO / "deploy" / "nginx.env.example"
COMPOSE = REPO / "docker-compose.yml"
LIB_SH = REPO / "deploy" / "cd" / "lib.sh"
DEPLOY_SH = REPO / "deploy" / "cd" / "deploy.sh"
BOOTSTRAP_SH = REPO / "deploy" / "cloud" / "bootstrap.sh"
PREPARE_STACK_SH = REPO / "deploy" / "ci" / "prepare-stack.sh"
NGINX_CONF = REPO / "deploy" / "nginx" / "nginx.conf"
PROXY_LOCATIONS_TEMPLATE = REPO / "deploy" / "nginx" / "templates" / "proxy_locations.conf.template"
TLS_TEMPLATE = REPO / "deploy" / "nginx" / "templates" / "tls.conf.template"
FRONTEND_SRC = REPO / "frontend" / "src"


def _read(path: Path) -> str:
    assert path.is_file(), f"文件不存在：{path}"
    return path.read_text(encoding="utf-8")


def _yaml_block(text: str, header: str, indent: int) -> str:
    """取 ``indent`` 级缩进的 ``header:`` 那一块（到下个同级或更浅的键为止）。

    刻意不引 PyYAML：这个模块的定位是「零依赖、任何环境都能跑」，用正则读
    这几个固定形状的块足够了。注释行和空行保留在块内（它们不影响下面的匹配）。
    """
    prefix = " " * indent + header + ":"
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if not inside:
            if line.startswith(prefix):
                inside = True
                out.append(line)
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        if len(line) - len(line.lstrip(" ")) <= indent:
            break
        out.append(line)
    assert out, f"docker-compose.yml 里找不到 {header!r} 块（缩进 {indent}）"
    return "\n".join(out)


def _first_group(pattern: str, text: str, what: str) -> str:
    # 全部 pattern 都用 ^ 表示行首，所以这里统一开 MULTILINE。
    m = re.search(pattern, text, re.MULTILINE)
    assert m, f"没匹配到{what}（pattern={pattern!r}）"
    return m.group(1)


@unittest.skip("direct sandbox MCP is intentionally disabled until a down-scoped capability proxy exists")
class TestSandboxMcpIpConsistency(unittest.TestCase):
    """mcp 的静态 IP 三处一致，且落在子网内。"""

    def test_ip_is_identical_across_three_places(self):
        env_ip = _first_group(r"^SANDBOX_MCP_HOST_IP=(\S+)\s*$", _read(ENV_EXAMPLE),
                              "deploy/.env.example 的 SANDBOX_MCP_HOST_IP")

        mcp_block = _yaml_block(_read(COMPOSE), "mcp", 2)
        compose_ip = _first_group(r"ipv4_address:\s*(\S+)", mcp_block,
                                  "docker-compose.yml 里 mcp 的 ipv4_address")

        lib_ip = _first_group(r'MCP_SANDBOX_IP="\$\{MCP_SANDBOX_IP:-([^}"]+)\}"',
                              _read(LIB_SH),
                              "deploy/cd/lib.sh 里 MCP_SANDBOX_IP 的默认值")

        self.assertEqual(
            env_ip, compose_ip,
            f"deploy/.env.example 的 SANDBOX_MCP_HOST_IP={env_ip} 与 "
            f"docker-compose.yml 里 mcp 的 ipv4_address={compose_ip} 不一致 —— "
            f"沙箱容器 /etc/hosts 会写成一个连不通的地址",
        )
        self.assertEqual(
            env_ip, lib_ip,
            f"deploy/.env.example 的 SANDBOX_MCP_HOST_IP={env_ip} 与 "
            f"deploy/cd/lib.sh 的 MCP_SANDBOX_IP 默认值={lib_ip} 不一致",
        )

    def test_ip_is_inside_the_mcp_sandbox_subnet(self):
        env_ip = _first_group(r"^SANDBOX_MCP_HOST_IP=(\S+)\s*$", _read(ENV_EXAMPLE),
                              "deploy/.env.example 的 SANDBOX_MCP_HOST_IP")

        net_block = _yaml_block(_read(COMPOSE), "mcp-sandbox", 2)
        subnet = _first_group(r"subnet:\s*(\S+)", net_block,
                              "docker-compose.yml 里 mcp-sandbox 的 subnet")

        self.assertIn(
            ipaddress.ip_address(env_ip),
            ipaddress.ip_network(subnet, strict=False),
            f"SANDBOX_MCP_HOST_IP={env_ip} 不在 mcp-sandbox 的子网 {subnet} 内 —— "
            f"compose 起不来，或者 mcp 拿不到这个地址",
        )

    def test_ipv4_address_appears_exactly_once(self):
        """整份 compose 只该有一处静态 IP。多一处通常是复制粘贴出来的。"""
        hits = re.findall(r"^\s*ipv4_address:", _read(COMPOSE), re.MULTILINE)
        self.assertEqual(
            len(hits), 1,
            f"docker-compose.yml 里有 {len(hits)} 处 ipv4_address，期望恰好 1 处"
            f"（mcp 的）。新增静态 IP 时要同步扩展本测试。",
        )


class TestNginxTlsSwitchTemplate(unittest.TestCase):
    """tls.conf 在 nginx.conf 的 http{} **顶层**被 include，那里只能用 map。

    真机发布时踩过：模板原本写 ``set $tls_enabled "...";``，而 set 属于
    rewrite 模块、只允许出现在 server/location/if，写在 http 层 nginx -t 直接
    ``"set" directive is not allowed here``，容器 restart 死循环、换版必回滚。
    CI 全新起栈没拦住（也没真跑 nginx -t），所以这里用静态断言钉死上下文。
    """

    @classmethod
    def setUpClass(cls):
        cls.template = _read(TLS_TEMPLATE)
        cls.conf = _read(NGINX_CONF)

    def _active_lines(self):
        # 注释行里会反复讨论 set/map，绝不能拿注释内容做断言 —— 只看有效行。
        return [
            ln for ln in self.template.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]

    def test_tls_conf_is_included_in_http_context(self):
        self.assertIn("include /etc/nginx/conf.d/tls.conf;", self.conf)
        include_at = self.conf.index("include /etc/nginx/conf.d/tls.conf;")
        m = re.search(r"^[ \t]*server\s*\{", self.conf, re.MULTILINE)
        self.assertIsNotNone(m, "nginx.conf 里没有 server 块？")
        self.assertLess(
            include_at, m.start(),
            "tls.conf 的 include 出现在第一个 server 块之后 —— 那就不在 http 顶层，"
            "本测试对 set/map 的上下文假设失效了，需要重审",
        )

    def test_switch_is_defined_with_map_not_set(self):
        active = "\n".join(self._active_lines())
        self.assertRegex(
            active, r"map\s+\$\w+\s+\$tls_enabled\s*\{",
            "TLS 开关必须在 http 层用 map 定义 $tls_enabled（set 在该上下文非法）",
        )
        self.assertNotRegex(
            active, r"(?m)^\s*set\s+",
            "tls.conf 在 http{} 顶层被 include，不能出现 set 指令 —— "
            "nginx -t 会 emerg '\"set\" directive is not allowed here'（真机复现）",
        )
        self.assertIn(
            "${TLS_ENABLED}", active,
            "模板必须引用容器环境变量 ${TLS_ENABLED}（由 20-envsubst 渲染）",
        )


class TestJwtAuthStructure(unittest.TestCase):
    """统一身份由 Java ERP 签发；nginx 只透传 Bearer，不再持有用户凭据。"""

    @classmethod
    def setUpClass(cls):
        cls.conf = _read(NGINX_CONF)
        cls.locations = _read(PROXY_LOCATIONS_TEMPLATE)
        cls.compose = _read(COMPOSE)
        cls.env = _read(ENV_EXAMPLE)

    def test_nginx_has_no_basic_or_trusted_identity_headers(self):
        self.assertNotIn("auth_basic", self.conf)
        self.assertNotIn("X-Authenticated-User", self.conf)
        self.assertNotIn("X-Internal-Auth", self.conf)
        self.assertNotIn("X-Authenticated-User", self.locations)
        self.assertNotIn("X-Internal-Auth", self.locations)

    def test_nginx_routes_identity_and_erp_to_java(self):
        self.assertEqual(self.conf.count("include /etc/nginx/conf.d/proxy_locations.conf;"), 2)
        self.assertEqual(self.locations.count("location /api/auth/"), 1)
        self.assertEqual(self.locations.count("location /api/erp/"), 1)
        self.assertGreaterEqual(self.locations.count("proxy_set_header Authorization"), 4)
        self.assertIn("http://java-erp:8080", self.locations)

    def test_compose_separates_private_and_public_keys(self):
        java = _yaml_block(self.compose, "java-erp", 2)
        backend = _yaml_block(self.compose, "backend", 2)
        mcp = _yaml_block(self.compose, "mcp", 2)
        self.assertIn("erp-jwt-private.pem", java)
        self.assertNotIn("erp-jwt-private.pem", backend)
        self.assertNotIn("erp-jwt-private.pem", mcp)
        self.assertIn("AUTH_MODE: jwt", backend)
        self.assertIn("MCP_AUTH_ENABLED", mcp)

    def test_env_declares_required_jwt_contract(self):
        for key in (
            "ERP_JWT_PRIVATE_KEY_PATH", "ERP_JWT_PUBLIC_KEY_PATH",
            "JWT_PUBLIC_KEY_PATH", "JWT_ISSUER", "JWT_AUDIENCE",
            "ERP_BOOTSTRAP_ADMIN_USERNAME", "ERP_BOOTSTRAP_ADMIN_PASSWORD",
        ):
            self.assertRegex(self.env, rf"(?m)^{key}=", f"缺少 {key}")

    def test_production_sync_preserves_runtime_keys(self):
        package_filter = _read(REPO / "deploy" / "cd" / "package.filter")
        self.assertIn("- /deploy/secrets/", package_filter)
        init_security = _read(REPO / "deploy" / "init-security.sh")
        self.assertIn("deploy/generate-jwt-keys.sh", init_security)
        self.assertIn("ERP_BOOTSTRAP_ADMIN_PASSWORD", init_security)


class TestEnvTemplates(unittest.TestCase):
    """nginx 模板只持有 TLS 开关，应用模板持有 JWT 路径而不含真实密钥。"""

    def test_nginx_env_contains_only_transport_switches(self):
        nginx_env = _read(NGINX_ENV_EXAMPLE)
        self.assertRegex(nginx_env, r"(?m)^TLS_ENABLED=")
        self.assertNotIn("PASSWORD=", nginx_env)
        self.assertNotIn("JWT_PRIVATE", nginx_env)

    def test_application_env_points_to_generated_keys(self):
        env = _read(ENV_EXAMPLE)
        self.assertIn("deploy/generate-jwt-keys.sh", env)
        self.assertIn("/run/secrets/erp-jwt-private.pem", env)
        self.assertIn("/run/secrets/erp-jwt-public.pem", env)


class TestFrontendIsEnvironmentIndependent(unittest.TestCase):
    """前端源码里不得出现硬编码的后端绝对地址。

    这是「同一个前端镜像在任何环境都能用」的第一道防线（第二道在 CI 的
    frontend job：扫**构建产物**）。两道都要：源码层能让人在 PR 里就看见
    失败原因，bundle 层才能抓住 NEXT_PUBLIC_* 构建期内联这类只在构建时
    发生的泄漏。

    正确做法是 frontend/src/lib/api.ts 的 `BASE_URL ?? "/api"` —— 相对路径，
    由 nginx 承担代理。
    """

    # 后端与 mcp 的容器内端口。它们绝不该出现在前端代码里。
    _BACKEND_URL = re.compile(r"https?://[A-Za-z0-9._-]+:(8000|9000|8081)\b")

    def test_no_hardcoded_backend_urls_in_source(self):
        offenders: list[str] = []
        for path in sorted(FRONTEND_SRC.rglob("*")):
            if not path.is_file() or path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if self._BACKEND_URL.search(line):
                    rel = path.relative_to(REPO).as_posix()
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")

        self.assertEqual(
            offenders, [],
            "前端源码里出现了硬编码的后端绝对地址：\n  "
            + "\n  ".join(offenders)
            + "\n\n这会让镜像依赖构建时的环境，破坏「同一个镜像在任何环境都能用」。"
            "\n正确做法是相对路径 '/api' + nginx 代理（见 frontend/src/lib/api.ts）。",
        )


if __name__ == "__main__":
    unittest.main()
