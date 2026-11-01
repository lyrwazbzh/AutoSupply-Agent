"""按沙箱代次隔离状态的基础设施熔断器。"""
import asyncio
import time
from threading import Lock
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from ..backends.custom_opensandbox import (
    SandboxFailure,
    SandboxFailureKind,
)
from ..log_utils import middleware_logger


class SandboxCircuitBreakerMiddleware(AgentMiddleware):
    """
    沙箱熔断器中间件

    三态模型：
    - CLOSED（正常）：所有工具调用正常通过
    - OPEN（熔断）：沙箱相关工具直接返回降级响应，不调用 handler
    - HALF_OPEN（探测）：熔断后经过 recovery_timeout，允许一次试探

    触发条件：同一个 ``sandbox_id + generation`` 连续发生
    ``failure_threshold`` 次基础设施故障；确定性硬故障立即 OPEN。
    恢复条件：同代等待 ``recovery_timeout`` 后仅允许一个健康探针；热替换为
    新 generation 后立即允许探针，不继承旧代的等待时间。

    仅拦截沙箱相关工具（execute, run_code 等），MCP/ERP 工具不受影响。
    """

    # 沙箱相关工具名（这些工具依赖沙箱容器）
    SANDBOX_TOOLS = {"execute", "run_code", "run_python", "shell", "bash"}
    COUNTED_FAILURES = {
        SandboxFailureKind.EXEC_TRANSPORT_ERROR,
        SandboxFailureKind.INFRA_TIMEOUT,
    }
    IMMEDIATE_OPEN_FAILURES = {
        SandboxFailureKind.CONTAINER_UNAVAILABLE,
        SandboxFailureKind.RESOURCE_EXHAUSTED,
    }

    def __init__(
        self,
        sandbox_backend,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        on_open: Callable[[], None] | None = None,
    ):
        self._sandbox_backend = sandbox_backend
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._on_open = on_open
        self._sandbox_key: tuple[str, int] | None = None
        self._failure_count: int = 0
        self._state: str = "CLOSED"  # CLOSED / OPEN / HALF_OPEN
        self._opened_at: float = 0.0
        self._probe_in_flight = False
        self._lock = Lock()
        self.tools = []

    @property
    def name(self) -> str:
        return "SandboxCircuitBreakerMiddleware"

    def set_on_open(self, callback: Callable[[], None] | None) -> None:
        self._on_open = callback

    def record_recovered_generation(self) -> None:
        """接收恢复流程已完成受控探针的通知，完成新代 HALF_OPEN → CLOSED。"""
        key = self._current_key()
        with self._lock:
            self._sandbox_key = key
            self._failure_count = 0
            self._state = "HALF_OPEN"
            self._probe_in_flight = False
            self._opened_at = 0.0
            self._state = "CLOSED"
        middleware_logger.info(
            "Circuit breaker HALF_OPEN → CLOSED after replacement probe "
            f"(id={key[0]}, generation={key[1]})"
        )

    def _is_sandbox_tool(self, tool_name: str) -> bool:
        """判断工具是否依赖沙箱"""
        return tool_name.lower() in self.SANDBOX_TOOLS

    def _current_key(self) -> tuple[str, int]:
        """读取 Proxy 原子暴露的当前沙箱身份。"""
        try:
            return self._sandbox_backend.identity
        except Exception as exc:
            raise SandboxFailure(
                SandboxFailureKind.CONTAINER_UNAVAILABLE,
                "No current sandbox generation available",
                code="sandbox_identity_unavailable",
                execution_state="NOT_STARTED",
            ) from exc

    def _sync_generation(self, key: tuple[str, int]) -> None:
        """新代沙箱不继承旧代计数和冷却时间，首次调用前进入探针态。"""
        with self._lock:
            if self._sandbox_key is None:
                self._sandbox_key = key
                return
            if self._sandbox_key == key:
                return
            self._sandbox_key = key
            self._failure_count = 0
            self._state = "HALF_OPEN"
            self._opened_at = 0.0
            self._probe_in_flight = False
            middleware_logger.info(
                "Circuit breaker → HALF_OPEN for new sandbox "
                f"(id={key[0]}, generation={key[1]})"
            )

    def _blocked_message(self, request: ToolCallRequest, tool_name: str) -> ToolMessage:
        return ToolMessage(
            content=(
                f"[沙箱暂时不可用] 工具 '{tool_name}' 被熔断器拦截。"
                "沙箱服务正在恢复中，请稍后重试或使用其他工具完成任务。"
            ),
            tool_call_id=request.tool_call.get("id", ""),
            status="error",
        )

    def _acquire_probe(self, key: tuple[str, int]) -> bool:
        """在状态锁内保证 HALF_OPEN 只放行一个健康探针。"""
        with self._lock:
            if self._sandbox_key != key:
                return False
            if self._state == "OPEN":
                if time.monotonic() - self._opened_at < self._recovery_timeout:
                    return False
                self._state = "HALF_OPEN"
            if self._state != "HALF_OPEN":
                return True
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    async def _probe(self, key: tuple[str, int]) -> bool:
        """执行受控 workspace 读写探针；普通工具不承担 HALF_OPEN 探测。"""
        try:
            healthy = await asyncio.to_thread(
                self._sandbox_backend.probe_workspace
            )
        except Exception:
            healthy = False
        try:
            current_key = self._current_key()
        except SandboxFailure as exc:
            self._on_failure(("unavailable", -1), "health_probe", exc)
            return False
        if current_key != key:
            self._sync_generation(current_key)
            return False
        with self._lock:
            if self._sandbox_key != key:
                return False
            self._probe_in_flight = False
            if healthy:
                self._failure_count = 0
                self._state = "CLOSED"
                middleware_logger.info(
                    "Circuit breaker → CLOSED after health probe "
                    f"(id={key[0]}, generation={key[1]})"
                )
            else:
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                middleware_logger.error(
                    "Circuit breaker → OPEN after failed health probe "
                    f"(id={key[0]}, generation={key[1]})"
                )
                self._notify_unhealthy()
        return healthy

    def _notify_unhealthy(self) -> None:
        if self._on_open is None:
            return
        try:
            self._on_open()
        except Exception as exc:
            middleware_logger.warning(
                f"Failed to notify sandbox health middleware: {exc}"
            )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """拦截沙箱工具调用，实现熔断逻辑"""
        tool_name = request.tool_call.get("name", "")

        # 非沙箱工具直接通过
        if not self._is_sandbox_tool(tool_name):
            return await handler(request)

        try:
            key = self._current_key()
        except SandboxFailure as exc:
            self._on_failure(("unavailable", -1), tool_name, exc)
            return self._blocked_message(request, tool_name)

        self._sync_generation(key)
        if not self._acquire_probe(key):
            middleware_logger.warning(
                f"Circuit breaker {self._state}: skipping sandbox tool '{tool_name}'"
            )
            return self._blocked_message(request, tool_name)

        with self._lock:
            probing = self._state == "HALF_OPEN" and self._probe_in_flight
        if probing and not await self._probe(key):
            return self._blocked_message(request, tool_name)

        try:
            result = await handler(request)
            # 热替换发生在调用过程中时，旧代结果不得改变新代状态或作为有效结果返回。
            current_key = self._current_key()
            if current_key != key:
                self._sync_generation(current_key)
                return self._failure_message(
                    request,
                    tool_name,
                    SandboxFailure(
                        SandboxFailureKind.GENERATION_STALE,
                        "本次调用所属容器代次已失效，请重新获取租约后重试",
                        execution_state="FINISHED",
                    ),
                )
            self._on_success(key)
            return result
        except SandboxFailure as exc:
            try:
                current_key = self._current_key()
            except SandboxFailure as hard_exc:
                self._on_failure(("unavailable", -1), tool_name, hard_exc)
                return self._blocked_message(request, tool_name)
            if current_key != key:
                self._sync_generation(current_key)
                return self._failure_message(
                    request,
                    tool_name,
                    SandboxFailure(
                        SandboxFailureKind.GENERATION_STALE,
                        "本次调用所属容器代次已失效，请重新获取租约后重试",
                        execution_state=exc.execution_state,
                    ),
                )
            if exc.kind in self.COUNTED_FAILURES | self.IMMEDIATE_OPEN_FAILURES:
                self._on_failure(key, tool_name, exc)
            return self._failure_message(request, tool_name, exc)
        except Exception as exc:
            # 未被基础设施后端明确分类的异常不参与熔断计数。
            return ToolMessage(
                content=f"[沙箱调用失败] {tool_name}: {str(exc)[:200]}",
                tool_call_id=request.tool_call.get("id", ""),
                status="error",
            )

    def _on_success(self, key: tuple[str, int]) -> None:
        """工具调用成功"""
        with self._lock:
            if self._sandbox_key != key:
                return
            self._failure_count = 0

    def _failure_message(
        self,
        request: ToolCallRequest,
        tool_name: str,
        failure: SandboxFailure,
    ) -> ToolMessage:
        return ToolMessage(
            content=(
                f"[沙箱调用失败:{failure.kind.value}] {tool_name}: "
                f"{str(failure)[:200]}"
            ),
            tool_call_id=request.tool_call.get("id", ""),
            status="error",
        )

    def _on_failure(
        self,
        key: tuple[str, int],
        tool_name: str,
        error: SandboxFailure,
    ) -> None:
        """按结构化故障策略累计或立即打开当前代熔断器。"""
        with self._lock:
            if self._sandbox_key != key:
                self._sandbox_key = key
                self._failure_count = 0
            immediate_open = error.kind in self.IMMEDIATE_OPEN_FAILURES
            if error.kind in self.COUNTED_FAILURES:
                self._failure_count += 1
            if immediate_open or self._failure_count >= self._failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                self._probe_in_flight = False
                middleware_logger.error(
                    f"Circuit breaker → OPEN for id={key[0]}, generation={key[1]} "
                    f"after {self._failure_count} counted failures. Last error: "
                    f"{error.kind.value}/{tool_name}: {error}"
                )
                self._notify_unhealthy()
                return
            middleware_logger.warning(
                f"Sandbox infrastructure failure "
                f"({self._failure_count}/{self._failure_threshold}) for "
                f"id={key[0]}, generation={key[1]}: "
                f"{error.kind.value}/{tool_name}: {error}"
            )
