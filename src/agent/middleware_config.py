"""
子Agent中间件工厂（Harness 架构）

子 Agent 栈（相对主 Agent 精简）：
1. SummarizationMiddleware      — 与主 Agent 相同的采购上下文压缩
2. ContextInjectionMiddleware   — 可信身份 / 偏好 / WARM
3. SandboxCircuitBreakerMiddleware — 沙箱工具熔断

项目中间件按同名替换 create_deep_agent 的默认摘要器，避免阈值和提示词漂移。
Skills 由主 Agent 的 SkillsLifecycleMiddleware 在每次运行开始时统一同步/恢复；
子 Agent 与主 Agent 共用同一个沙箱，不再各自维护第二套同步缓存。
ERPWriteMiddleware 由 main_agent 在工厂结果上追加。
"""
from .context_compaction import create_context_compaction_middleware
from .middlewares.context_injection import ContextInjectionMiddleware
from .middlewares.sandbox_breaker import SandboxCircuitBreakerMiddleware
from .schema import ProcurementContext


def get_analyst_middleware(
    sandbox_backend,
    user_context: ProcurementContext | None = None,
    *,
    model=None,
    compaction_backend=None,
) -> list:
    """采购分析子Agent中间件。"""
    context = user_context or ProcurementContext(username="采购分析师")

    middleware = []
    if model is not None and compaction_backend is not None:
        middleware.append(
            create_context_compaction_middleware(
                model=model,
                backend=compaction_backend,
            )
        )
    middleware.extend([
        ContextInjectionMiddleware(user_context=context),
        SandboxCircuitBreakerMiddleware(
            sandbox_backend=sandbox_backend,
            failure_threshold=3,
            recovery_timeout=60,
        ),
    ])
    return middleware


def get_order_middleware(
    sandbox_backend,
    user_context: ProcurementContext | None = None,
    *,
    model=None,
    compaction_backend=None,
) -> list:
    """采购订单子Agent中间件。"""
    context = user_context or ProcurementContext(username="采购订单专员")

    middleware = []
    if model is not None and compaction_backend is not None:
        middleware.append(
            create_context_compaction_middleware(
                model=model,
                backend=compaction_backend,
            )
        )
    middleware.extend([
        ContextInjectionMiddleware(user_context=context),
        SandboxCircuitBreakerMiddleware(
            sandbox_backend=sandbox_backend,
            failure_threshold=3,
            recovery_timeout=60,
        ),
    ])
    return middleware


def get_all_subagent_middlewares(
    sandbox_backend,
    user_context: ProcurementContext | None = None,
    *,
    model=None,
    compaction_backend=None,
) -> dict[str, list]:
    """{subagent_name: middleware_list}，供 main_agent 统一加载。"""
    return {
        "procurement-analyst": get_analyst_middleware(
            sandbox_backend,
            user_context,
            model=model,
            compaction_backend=compaction_backend,
        ),
        "procurement-order": get_order_middleware(
            sandbox_backend,
            user_context,
            model=model,
            compaction_backend=compaction_backend,
        ),
    }
