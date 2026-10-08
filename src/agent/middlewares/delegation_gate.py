"""
Task 委派中间件：DeepAgents ``task`` 工具的工程化门禁、观测与回流核验。

委托 ``TaskDispatchGate`` 完成校验/注入/核验；本文件负责挂 LangChain 工具链与超时包装。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from ..log_utils import middleware_logger
from ..schema import ProcurementContext
from ..subagents.task_dispatch import (
    DEFAULT_DISPATCH_TIMEOUT_S,
    DEFAULT_MAX_PARALLEL,
    SubAgentRegistry,
    TaskDispatchGate,
    TaskDispatchService,
)

DELEGATION_TOOL_NAMES = frozenset({"task"})


class TaskDispatchMiddleware(AgentMiddleware):
    """拦截并增强 DeepAgents 的 ``task`` 委派调用。"""

    def __init__(
        self,
        registry: SubAgentRegistry,
        user_context: ProcurementContext | None = None,
        *,
        min_description_chars: int = 24,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
        timeout_s: float = DEFAULT_DISPATCH_TIMEOUT_S,
    ):
        self.tools = []
        service = TaskDispatchService(
            registry,
            user_context,
            min_description_chars=min_description_chars,
            max_parallel=max_parallel,
            timeout_s=timeout_s,
        )
        self._gate = TaskDispatchGate(service)
        self._service = service

    @property
    def name(self) -> str:
        return "TaskDispatchMiddleware"

    def _call_id(self, request: ToolCallRequest) -> str:
        return str(request.tool_call.get("id", "") or "")

    def _args(self, request: ToolCallRequest) -> dict[str, Any]:
        args = request.tool_call.get("args") or {}
        return dict(args) if isinstance(args, dict) else {}

    def _tool_message(
        self, request: ToolCallRequest, content: str, *, status: str = "error"
    ) -> ToolMessage:
        return ToolMessage(
            content=content,
            tool_call_id=self._call_id(request),
            name=str(request.tool_call.get("name", "task") or "task"),
            status=status,
        )

    def _apply_enriched_description(
        self, request: ToolCallRequest, enriched: str
    ) -> None:
        args = self._args(request)
        args["description"] = enriched
        tool_call = dict(request.tool_call)
        tool_call["args"] = args
        request.tool_call = tool_call

    def _prepare(self, request: ToolCallRequest) -> ToolMessage | None:
        tool_name = str(request.tool_call.get("name", "") or "")
        if tool_name not in DELEGATION_TOOL_NAMES:
            return None

        args = self._args(request)
        decision = self._gate.before_call(
            args.get("subagent_type"),
            args.get("description"),
            self._call_id(request),
        )
        if decision.action == "reject":
            middleware_logger.info(
                f"TaskDispatch blocked '{tool_name}': {decision.reason}"
            )
            return self._tool_message(
                request, f"[委派被拒绝] {decision.reason}", status="error"
            )

        self._apply_enriched_description(request, decision.enriched_description)
        middleware_logger.info(
            "TaskDispatch start: "
            f"filled={sorted(decision.filled_fields)} "
            f"parallel={self._service.active_count}/{self._service.max_parallel}"
        )
        return None

    def _finalize_result(
        self,
        request: ToolCallRequest,
        result: ToolMessage | Command[Any],
    ) -> ToolMessage | Command[Any]:
        call_id = self._call_id(request)

        if not isinstance(result, ToolMessage):
            self._service.end(call_id, status="completed")
            return result

        content = (
            result.content if isinstance(result.content, str) else str(result.content)
        )
        is_error = getattr(result, "status", None) == "error"
        decision = self._gate.after_result(call_id, content, is_error=is_error)
        middleware_logger.info(
            f"TaskDispatch end: status={decision.end_status} action={decision.action}"
        )
        if decision.action == "replace":
            return self._tool_message(
                request, decision.replace_content, status="error"
            )
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        rejected = self._prepare(request)
        if rejected is not None:
            return rejected
        if str(request.tool_call.get("name", "") or "") not in DELEGATION_TOOL_NAMES:
            return handler(request)
        call_id = self._call_id(request)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(handler, request)
                try:
                    result = future.result(timeout=self._service.timeout_s)
                except concurrent.futures.TimeoutError:
                    decision = self._gate.on_timeout(call_id)
                    return self._tool_message(
                        request, decision.replace_content, status="error"
                    )
            return self._finalize_result(request, result)
        except Exception as exc:
            self._gate.on_exception(call_id, exc)
            raise

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        rejected = self._prepare(request)
        if rejected is not None:
            return rejected
        if str(request.tool_call.get("name", "") or "") not in DELEGATION_TOOL_NAMES:
            return await handler(request)
        call_id = self._call_id(request)
        try:
            result = await asyncio.wait_for(
                handler(request), timeout=self._service.timeout_s
            )
            return self._finalize_result(request, result)
        except asyncio.TimeoutError:
            decision = self._gate.on_timeout(call_id)
            return self._tool_message(
                request, decision.replace_content, status="error"
            )
        except Exception as exc:
            self._gate.on_exception(call_id, exc)
            raise


DelegationGateMiddleware = TaskDispatchMiddleware
