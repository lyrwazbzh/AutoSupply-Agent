"""一轮结束后的记忆维护：偏好合并（WARM）+ 情节归档/遗忘（COLD）。"""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, Runtime

from ..memory.config import DEFAULT_MEMORY_CONFIG, MemoryConfig
from .memory_consolidation import MemoryConsolidationMiddleware
from .memory_update import MemoryUpdateMiddleware


class MemoryLifecycleMiddleware(AgentMiddleware):
    """把原先拆开的两个 after_agent 记忆中间件收成一条写路径。"""

    def __init__(
        self,
        store=None,
        user_id: str = "default_user",
        config: MemoryConfig | None = None,
    ):
        cfg = config or DEFAULT_MEMORY_CONFIG
        self._update = MemoryUpdateMiddleware(
            store=store, user_id=user_id, config=cfg
        )
        self._consolidation = MemoryConsolidationMiddleware(
            store=store, user_id=user_id, config=cfg
        )
        self.tools = []

    @property
    def name(self) -> str:
        return "MemoryLifecycleMiddleware"

    def after_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        self._update.after_agent(state, runtime)
        self._consolidation.after_agent(state, runtime)
        return None
