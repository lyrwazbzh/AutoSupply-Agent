"""沙箱健康检查与透明恢复中间件。"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from threading import Lock
from typing import Any

from langchain.agents.middleware import AgentMiddleware, Runtime

from ..log_utils import middleware_logger


class SandboxHealthMiddleware(AgentMiddleware):
    """在每次 Agent 运行前验证并在需要时重建用户沙箱。

    ``CompositeBackend``、文件工具和自定义工具都持有同一个
    :class:`SandboxBackendProxy`。故障时这里只替换 Proxy 的底层后端，再执行
    bootstrap 回调，因此无需重新创建 Agent 或丢失会话图状态。
    """

    def __init__(
        self,
        sandbox_manager=None,
        user_id: str = "default_user",
        sandbox_backend=None,
        prepare_replacement: Callable[[Any], None] | None = None,
        on_rebuild: Callable[[Any], None] | None = None,
        on_recovered: Callable[[], None] | None = None,
        check_interval: float = 30.0,
        failure_threshold: int = 1,
    ):
        self._sandbox_manager = sandbox_manager
        self._user_id = user_id
        self._sandbox_backend = sandbox_backend
        self._prepare_replacement = prepare_replacement
        self._on_rebuild = on_rebuild
        self._on_recovered = on_recovered
        self._check_interval = check_interval
        self._failure_threshold = max(1, failure_threshold)
        self._last_check: float = 0.0
        self._healthy = True
        self._consecutive_failures = 0
        self._recovery_failures = 0
        self._next_recovery_at = 0.0
        self._recovery_lock = Lock()
        self.tools = []

    @property
    def name(self) -> str:
        return "SandboxHealthMiddleware"

    def before_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        """同步入口，兼容非流式调用。"""
        self._check_and_recover()
        return None

    async def abefore_agent(
        self, state: Any, runtime: Runtime
    ) -> dict[str, Any] | None:
        """流式路径在线程中执行 Docker/PostgreSQL I/O，避免阻塞事件循环。"""
        await asyncio.to_thread(self._check_and_recover)
        return None

    def _check_and_recover(self) -> None:
        # LocalShell fallback 没有 Manager，保持原有开发模式语义。
        if self._sandbox_manager is None or self._sandbox_backend is None:
            self._healthy = True
            return

        now = time.monotonic()
        backend_ready = bool(getattr(self._sandbox_backend, "ready", True))
        if (
            self._healthy
            and backend_ready
            and now - self._last_check < self._check_interval
        ):
            return
        self._last_check = now

        if backend_ready and self._ping_sandbox():
            self._healthy = True
            self._consecutive_failures = 0
            touch = getattr(self._sandbox_manager, "touch", None)
            if callable(touch):
                touch(self._user_id)
            middleware_logger.debug(
                f"Sandbox health check OK for user {self._user_id}"
            )
            return

        self._healthy = False
        self._consecutive_failures += 1
        middleware_logger.warning(
            "Sandbox health check failed for "
            f"{self._user_id} ({self._consecutive_failures} consecutive)"
        )
        if self._consecutive_failures < self._failure_threshold:
            return

        if now < self._next_recovery_at:
            remaining = max(1, int(self._next_recovery_at - now))
            raise RuntimeError(
                f"Sandbox recovery is backing off; retry in {remaining}s"
            )

        if not self._recovery_lock.acquire(blocking=False):
            raise RuntimeError("Sandbox recovery is already in progress")
        try:
            # 获取锁后再次检查，避免等待期间已有调用完成恢复。
            if self._healthy and bool(getattr(self._sandbox_backend, "ready", True)):
                return
            self._rebuild_sandbox()
        finally:
            self._recovery_lock.release()

    def _rebuild_sandbox(self) -> None:
        """重建、热替换并重新填充沙箱；任一环节失败都会在下一次请求重试。"""
        try:
            middleware_logger.info(
                f"Rebuilding unhealthy sandbox for user {self._user_id}"
            )
            replacement = self._sandbox_manager.rebuild(self._user_id)

            # 候选容器先完成核心 bootstrap，再发布到稳定 Proxy。这样并发调用
            # 不会看到一个尚未初始化完成的新 generation。
            if self._prepare_replacement is not None:
                self._prepare_replacement(replacement)

            replace_backend = getattr(self._sandbox_backend, "replace_backend", None)
            if not callable(replace_backend):
                raise RuntimeError("managed sandbox backend does not support hot replacement")
            replace_backend(replacement)

            probe_workspace = getattr(self._sandbox_backend, "probe_workspace", None)
            if (
                not callable(probe_workspace)
                or not probe_workspace(publish_ready=True)
            ):
                raise RuntimeError("replacement sandbox failed workspace health probe")
            if self._on_recovered is not None:
                self._on_recovered()

            # 用户 Skill 属于可降级能力：恢复失败记录告警，但不能让一个已健康的
            # 基础沙箱反复进入重建循环。
            if self._on_rebuild is not None:
                try:
                    self._on_rebuild(replacement)
                except Exception as exc:
                    middleware_logger.warning(
                        f"Sandbox recovered but optional capability restore failed: {exc}",
                        exc_info=True,
                    )

            touch = getattr(self._sandbox_manager, "touch", None)
            if callable(touch):
                touch(self._user_id)
            self._healthy = True
            self._consecutive_failures = 0
            self._recovery_failures = 0
            self._next_recovery_at = 0.0
            middleware_logger.info(
                f"Sandbox recovery complete for user {self._user_id}"
            )
        except Exception as exc:
            self._healthy = False
            self._recovery_failures += 1
            delay_index = min(self._recovery_failures - 1, 2)
            delay = (60.0, 120.0, 300.0)[delay_index]
            self._next_recovery_at = time.monotonic() + delay
            middleware_logger.error(
                f"Sandbox recovery failed for {self._user_id}: {exc}; "
                f"next attempt in {int(delay)}s",
                exc_info=True,
            )
            # 健康检查失败不应让中间件静默继续把请求交给失效容器。
            raise RuntimeError(f"Sandbox recovery failed: {exc}") from exc

    def mark_unhealthy(self) -> None:
        """由熔断器通知健康检查在下一次请求立即复核，而不是等待检查周期。"""
        self._healthy = False
        self._last_check = 0.0

    def _ping_sandbox(self) -> bool:
        """优先通过稳定 Proxy 探测当前底层容器。"""
        try:
            ping = getattr(self._sandbox_backend, "ping", None)
            if callable(ping):
                return bool(ping())
            response = self._sandbox_backend.execute("echo ok", timeout=5)
            return response.exit_code == 0
        except Exception:
            return False
