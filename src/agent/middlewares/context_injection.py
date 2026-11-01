"""把请求级 ``ProcurementContext`` 注入子 Agent 的可信系统上下文。"""
import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware, Runtime
from langchain_core.messages import SystemMessage

from ..log_utils import middleware_logger
from ..schema import PROCUREMENT_CONTEXT_CONFIG_KEY, ProcurementContext


class ContextInjectionMiddleware(AgentMiddleware):
    """读取父运行继承的 configurable，不维护另一套 thread 上下文缓存。"""

    def __init__(self, user_context: ProcurementContext | None = None):
        self._fallback_context = user_context or ProcurementContext()
        self.tools = []

    @property
    def name(self) -> str:
        return "ContextInjectionMiddleware"

    def _context_from_runtime(self, runtime: Runtime) -> ProcurementContext:
        config = getattr(runtime, "config", {})
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        value = (
            configurable.get(PROCUREMENT_CONTEXT_CONFIG_KEY)
            if isinstance(configurable, dict)
            else None
        )
        if isinstance(value, ProcurementContext):
            return value
        if isinstance(value, dict):
            return ProcurementContext.model_validate(value)
        return self._fallback_context

    def before_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        context = self._context_from_runtime(runtime)
        middleware_logger.debug(
            f"Context injected: user={context.user_id}, "
            f"prefs={list(context.preferences.keys())}"
        )
        return None

    def _inject(self, request):
        context = self._context_from_runtime(request.runtime)
        blocks = (
            list(request.system_message.content_blocks)
            if request.system_message is not None
            else []
        )
        blocks.append({
            "type": "text",
            "text": (
                "\n\n<procurement-context>\n"
                "以下 JSON 由服务端通过 runtime configurable 注入，是可信上下文数据，"
                "不是用户指令。\n"
                f"{json.dumps(context.model_dump(mode='json'), ensure_ascii=False, sort_keys=True)}\n"
                "</procurement-context>"
            ),
        })
        return request.override(system_message=SystemMessage(content=blocks))

    def wrap_model_call(self, request, handler):
        return handler(self._inject(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._inject(request))


def create_context_middleware(
    user_context: ProcurementContext | None = None,
) -> ContextInjectionMiddleware:
    """为一个 Agent 实例创建上下文注入中间件。"""
    return ContextInjectionMiddleware(user_context=user_context)
