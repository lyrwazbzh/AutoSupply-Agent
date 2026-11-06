"""沙箱 Skills 启停：仓库基础技能同步 + 用户持久技能恢复。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, Runtime

from .skills_sync import SkillsSyncMiddleware
from .user_skills_restore import UserSkillsRestoreMiddleware


class SkillsLifecycleMiddleware(AgentMiddleware):
    """主 Agent 侧把两个 before_agent Skills 步骤收成一条。"""

    def __init__(
        self,
        *,
        skills_dir: str | Path | None = None,
        sandbox_backend=None,
        store=None,
        user_id: str = "default_user",
    ):
        self._sync = SkillsSyncMiddleware(
            skills_dir=skills_dir,
            sandbox_backend=sandbox_backend,
        )
        self._restore = UserSkillsRestoreMiddleware(
            store=store,
            user_id=user_id,
            sandbox_backend=sandbox_backend,
        )
        self.tools = []

    @property
    def name(self) -> str:
        return "SkillsLifecycleMiddleware"

    def before_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        self._sync.before_agent(state, runtime)
        self._restore.before_agent(state, runtime)
        return None

    async def abefore_agent(
        self, state: Any, runtime: Runtime
    ) -> dict[str, Any] | None:
        await self._sync.abefore_agent(state, runtime)
        await self._restore.abefore_agent(state, runtime)
        return None

    def invalidate(self) -> None:
        self._sync.invalidate()
        self._restore.invalidate()

    def sync_now(self) -> None:
        self._sync.sync_now()

    def restore_now(self) -> None:
        self._restore.restore_now()
