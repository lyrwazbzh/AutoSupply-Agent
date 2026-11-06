"""
子Agent中间件工厂（Harness 架构）

子 Agent 栈（相对主 Agent 精简）：
1. ContextInjectionMiddleware   — 可信身份 / 偏好 / WARM
2. SkillsSyncMiddleware         — 仓库 Skills → 沙箱
3. SandboxCircuitBreakerMiddleware — 沙箱工具熔断

摘要压缩由 create_deep_agent 子图基线里的 SummarizationMiddleware 承担。
ERPWriteMiddleware 由 main_agent 在工厂结果上追加。
"""
from pathlib import Path

from .middlewares.context_injection import ContextInjectionMiddleware
from .middlewares.sandbox_breaker import SandboxCircuitBreakerMiddleware
from .middlewares.skills_sync import SkillsSyncMiddleware
from .schema import ProcurementContext

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def get_analyst_middleware(sandbox_backend, user_context: ProcurementContext | None = None) -> list:
    """采购分析子Agent中间件。"""
    context = user_context or ProcurementContext(username="采购分析师")

    return [
        ContextInjectionMiddleware(user_context=context),
        SkillsSyncMiddleware(
            skills_dir=SKILLS_DIR,
            sandbox_backend=sandbox_backend,
        ),
        SandboxCircuitBreakerMiddleware(
            sandbox_backend=sandbox_backend,
            failure_threshold=3,
            recovery_timeout=60,
        ),
    ]


def get_order_middleware(sandbox_backend, user_context: ProcurementContext | None = None) -> list:
    """采购订单子Agent中间件。"""
    context = user_context or ProcurementContext(username="采购订单专员")

    return [
        ContextInjectionMiddleware(user_context=context),
        SkillsSyncMiddleware(
            skills_dir=SKILLS_DIR,
            sandbox_backend=sandbox_backend,
        ),
        SandboxCircuitBreakerMiddleware(
            sandbox_backend=sandbox_backend,
            failure_threshold=3,
            recovery_timeout=60,
        ),
    ]


def get_all_subagent_middlewares(
    sandbox_backend,
    user_context: ProcurementContext | None = None,
) -> dict[str, list]:
    """{subagent_name: middleware_list}，供 main_agent 统一加载。"""
    return {
        "procurement-analyst": get_analyst_middleware(sandbox_backend, user_context),
        "procurement-order": get_order_middleware(sandbox_backend, user_context),
    }
