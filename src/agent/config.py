"""
全局配置模块
LLM、Store、Checkpointer、沙箱连接参数
"""
from langchain_openai import ChatOpenAI

from .env_utils import get_env, get_env_float, get_env_int

# ============ LLM 配置 ============
# ChatAnywhere：OpenAI 兼容的 API 网关，支持 gpt-4o / claude / deepseek 等模型。
# 文档：https://chatanywhere.apifox.cn
LLM_MODEL = get_env("LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = get_env("LLM_BASE_URL", "https://api.chatanywhere.tech/v1")
LLM_API_KEY = get_env("CHATANYWHERE_API_KEY", "")
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 4096
LLM_TIMEOUT_SECONDS = get_env_int("LLM_TIMEOUT_SECONDS", 120)


def get_llm(*, thinking: bool = True, timeout: float | None = None,
            max_retries: int = 2, max_tokens: int = LLM_MAX_TOKENS) -> ChatOpenAI:
    """获取 ChatOpenAI 模型实例（通过 ChatAnywhere 网关）。

    主 Agent 使用默认配置；需要强制结构化输出的内部评审器使用
    非思考模式（显式设置 temperature），避免 reasoning 模型拒绝
    ``tool_choice`` 参数。
    """
    common_kwargs = {
        "model": LLM_MODEL,
        "base_url": LLM_BASE_URL,
        "api_key": LLM_API_KEY,
        "max_tokens": max_tokens,
        "max_retries": max_retries,
    }
    common_kwargs["timeout"] = (
        timeout if timeout is not None else LLM_TIMEOUT_SECONDS
    )
    if thinking:
        # 思考模式：不设 temperature（reasoning 模型通常忽略或拒绝该参数）
        return ChatOpenAI(**common_kwargs)

    # DeepSeek 默认开启思考模式；仅设置 temperature 并不会关闭它。结构化输出
    # 会强制 tool_choice，而 DeepSeek 在思考模式下拒绝 required/指定工具，返回
    # HTTP 400。因此 Grader、路由器等结构化调用必须显式切到非思考模式。
    if "api.deepseek.com" in LLM_BASE_URL.lower():
        common_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(
        **common_kwargs,
        temperature=LLM_TEMPERATURE,
    )


# ============ MCP Server 配置 ============
MCP_SERVER_URL = get_env("MCP_SERVER_URL", "http://localhost:9000")
MCP_SSE_URL = f"{MCP_SERVER_URL}/sse"

# ============ Docker 连接配置 ============
# 客户端连接哪个 daemon 由 docker SDK 自己从环境变量读取，这里不重复解析：
#   - 容器部署指向 dind：DOCKER_HOST=tcp://dind:2375
#     （docker:dind 必须同时设 DOCKER_TLS_CERTDIR="" 才会监听明文 2375）
#   - 接外部远程 daemon：DOCKER_HOST=tcp://host:2376，并同时提供
#     DOCKER_TLS_VERIFY=1 与 DOCKER_CERT_PATH=/certs/client
# 两组取值互斥：对着 dind 的明文端口带 TLS 变量会握手失败。
#
# docker SDK 默认单次 API 调用超时 60s，扛不住 dind 冷启动时 containers.run
# 里夹着的镜像 pull，会直接 ReadTimeout。
#
# 这个值同时是沙箱内 timeout(1) 的上限：exec_run 是同步 HTTP 请求，容器内的
# 超时必须先触发，否则这里先 ReadTimeout，失败就丢了原因（见
# custom_opensandbox.execute 的 clamp）。sandbox_setup 里最长的单命令超时是
# 900s（Go 运行时安装），所以默认值必须明显大于 900 —— 300 会让那些安装永远
# 只能跑 270s 就被 socket 超时打断。
DOCKER_TIMEOUT_SECONDS = get_env_int("DOCKER_TIMEOUT_SECONDS", 1200)

# ============ 对外访问配置 ============
# 生成给用户看的下载链接用的根地址。必须是浏览器可达的地址，
# 不是容器内部的 http://backend:8000。
PUBLIC_BASE_URL = get_env("PUBLIC_BASE_URL", "http://localhost:8000")
# 逗号分隔的 CORS 白名单。走 nginx 同源后本项是 no-op，只在直连后端时生效。
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in get_env("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
# 沙箱不可用时是否允许退回到 LocalShellBackend / 无安全参数的容器。
# 本机开发可开；容器部署必须为 false —— local shell 会在 backend 进程环境
# （含 CHATANYWHERE_API_KEY、可写的 skills 挂载）里执行模型生成的代码。
ALLOW_LOCAL_SHELL_FALLBACK = get_env(
    "ALLOW_LOCAL_SHELL_FALLBACK", "true"
).lower() in ("1", "true", "yes")

# ============ 认证 ============
# none = 本机离线开发，不执行认证
# jwt  = 校验 Java ERP 签发的 RS256 访问令牌（默认容器部署）
#
# 生产固定使用 jwt：Java ERP 签发 RS256 令牌，backend 验签并检查 audience，
# 再通过 /api/auth/me 确认账号仍有效。none 只供本机离线开发，
# 不得用于容器生产环境。
AUTH_MODE = get_env("AUTH_MODE", "none").strip().lower()
JWT_PUBLIC_KEY_PATH = get_env("JWT_PUBLIC_KEY_PATH", "").strip()
JWT_ISSUER = get_env("JWT_ISSUER", "java-erp").strip()
JWT_AUDIENCE = get_env("JWT_AUDIENCE", "assistant-api").strip()
ERP_BASE_URL = get_env("ERP_BASE_URL", "http://localhost:8080").rstrip("/")
JWT_ACTIVE_CHECK_ENABLED = get_env("JWT_ACTIVE_CHECK_ENABLED", "true").lower() in ("1", "true", "yes")

# ============ 沙箱配置 ============
# 沙箱镜像。容器化部署默认 erp-sandbox:3.11（由 compose 的 sandbox-image-loader
# 用 deploy/sandbox/Dockerfile 在 dind 里构建，预装 matplotlib/pandas/numpy 与
# 中文字体）；本地开发未构建该镜像时保持 python:3.11-slim，依赖退回运行时按需安装
SANDBOX_IMAGE = get_env("SANDBOX_IMAGE", "python:3.11-slim")
SANDBOX_WORK_DIR = "/workspace"
SANDBOX_SKILLS_DIR = "/skills"
SANDBOX_MEMORIES_DIR = "/memories"
SANDBOX_WARM_POOL_SIZE = get_env_int("SANDBOX_WARM_POOL_SIZE", 1)

# 单条沙箱命令的默认超时（模型可以按次覆盖）。SDK 自己的 DEFAULT_EXECUTE_TIMEOUT
# 是 120s，但这个默认值在我们的 execute() 学会真正下发 timeout(1) 之前一直是
# 空转的，所以它从"形同虚设"变成了硬上限。本项目 AGENTS.md 要求脚本开头
# `pip install -q mcp`，图表任务还要装 matplotlib/numpy，慢网络下 120s 不够。
# 上限仍是 DOCKER_TIMEOUT_SECONDS（见 custom_opensandbox.execute 的 clamp）。
SANDBOX_EXECUTE_TIMEOUT_SECONDS = get_env_int("SANDBOX_EXECUTE_TIMEOUT_SECONDS", 300)
SANDBOX_IDLE_TIMEOUT_MINUTES = get_env_int("SANDBOX_IDLE_TIMEOUT_MINUTES", 30)
SANDBOX_MAINTENANCE_INTERVAL_SECONDS = get_env_int(
    "SANDBOX_MAINTENANCE_INTERVAL_SECONDS", 60
)
SANDBOX_HEALTH_CHECK_INTERVAL_SECONDS = get_env_int(
    "SANDBOX_HEALTH_CHECK_INTERVAL_SECONDS", 30
)

# 沙箱内访问 MCP Server 的地址。两个都为空 = 不注入，沙箱内无 MCP 能力
# （本机开发、或不想开放这条通路时就是这么用的）。
#
# 为什么需要 HOST_IP 这种别扭的东西：沙箱容器跑在 dind 自己的 bridge 网络
# 里，既解析不了 compose 的服务名（dind 的内嵌 DNS 不认识 `mcp`），也和 mcp
# 不在同一个二层网络。所以由 backend 把 mcp 在 mcp-sandbox 网络上的**静态
# IP** 写进沙箱容器的 /etc/hosts，流量经 dind 转发 + MASQUERADE 出去。
# 用静态 IP 而不是每次解析，是为了避免 mcp 容器重建换 IP 后沙箱里的地址失效。
SANDBOX_MCP_URL = get_env("SANDBOX_MCP_URL", "")
SANDBOX_MCP_HOST_IP = get_env("SANDBOX_MCP_HOST_IP", "")

# ============ Store 命名空间 ============
SKILLS_STORE_NAMESPACE = ("persisted-skills",)

def skills_store_namespace(user_id: str) -> tuple[str, str]:
    """Return the isolated Store namespace for one user's custom Skills."""
    return (*SKILLS_STORE_NAMESPACE, user_id)

# ============ Agent 配置 ============
MAX_MODEL_CALLS = get_env_int("MAX_MODEL_CALLS", 50)
MAX_TOOL_CALLS = get_env_int("MAX_TOOL_CALLS", 30)
AGENT_SESSION_TTL_SECONDS = get_env_int("AGENT_SESSION_TTL_SECONDS", 1800)
AGENT_SESSION_MAX_ENTRIES = get_env_int("AGENT_SESSION_MAX_ENTRIES", 128)
AGENT_RUN_LEASE_TTL_SECONDS = get_env_int("AGENT_RUN_LEASE_TTL_SECONDS", 180)

# 上下文压缩不再依赖模型名称推断窗口大小。ChatAnywhere 可能把同一个模型名
# 路由到不同提供方，所以部署者必须同时声明真实输入窗口。压缩模块会在 Agent
# 创建时校验三个值，并把比例换算成绝对 token 数交给 DeepAgents。
LLM_CONTEXT_WINDOW_TOKENS = get_env_int("LLM_CONTEXT_WINDOW_TOKENS", 128_000)
CONTEXT_COMPACTION_TRIGGER_RATIO = get_env_float(
    "CONTEXT_COMPACTION_TRIGGER_RATIO", 0.75
)
CONTEXT_COMPACTION_KEEP_RATIO = get_env_float(
    "CONTEXT_COMPACTION_KEEP_RATIO", 0.15
)
CONTEXT_SUMMARY_SCHEMA_VERSION = get_env(
    "CONTEXT_SUMMARY_SCHEMA_VERSION", "procurement-v1"
).strip()
