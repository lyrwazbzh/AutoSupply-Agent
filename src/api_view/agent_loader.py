"""
AgentLoader 单例
持有 agent 实例、PostgreSQL 资源、create_config、save/get_display_messages
"""
import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from ..agent.audit.repository import WriteAuditRepository
from ..agent.config import AGENT_SESSION_MAX_ENTRIES, AGENT_SESSION_TTL_SECONDS
from ..agent.log_utils import web_logger
from ..agent.schema import PROCUREMENT_CONTEXT_CONFIG_KEY, ProcurementContext
from ..runtime_state import (
    LeaseHandle,
    RuntimeLeaseConflict,
    RuntimeStateRepository,
    new_instance_id,
)
from .app_repository import AppRepository


@dataclass
class AgentSession:
    """一个用户独享的 Agent、稳定沙箱 Proxy 与串行运行锁。"""

    user_id: str
    username: str
    roles: frozenset[str]
    permissions: frozenset[str]
    authz_version: int
    capability_fingerprint: tuple
    agent: Any
    run_lock: asyncio.Lock
    warm_memory_middleware: Any
    user_context: ProcurementContext
    created_at: float
    last_accessed_at: float
    ownership_lease: LeaseHandle


class AgentLoader:
    """Agent 加载器单例 - 管理 Agent 生命周期."""

    _instance: Optional['AgentLoader'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.agent = None
        self._checkpointer = None
        self._store = None
        self._resources_ready = False
        self._pg_pool = None
        self._async_pg_pool = None
        self._app_repository: AppRepository | None = None
        self._write_audit_repository: WriteAuditRepository | None = None
        self._runtime_state_repository: RuntimeStateRepository | None = None
        self.instance_id = new_instance_id()
        self._sessions: dict[str, AgentSession] = {}
        self._resources_lock: asyncio.Lock | None = None
        self._sessions_lock: asyncio.Lock | None = None
        self._session_build_locks: dict[str, asyncio.Lock] = {}
        web_logger.info("AgentLoader initialized")

    @staticmethod
    def _capability_fingerprint(
        user_id: str,
        username: str,
        roles: frozenset[str],
        permissions: frozenset[str],
        authz_version: int,
    ) -> tuple:
        """只包含影响 Agent 能力的稳定身份，不包含短期 access token。"""
        return (
            user_id,
            username,
            tuple(sorted(roles)),
            tuple(sorted(permissions)),
            int(authz_version),
        )

    def _prune_sessions_locked(
        self, now: float, *, incoming_user_id: str
    ) -> list[AgentSession]:
        """在 ``_sessions_lock`` 内执行 TTL 与 LRU 淘汰，运行中的会话不驱逐。"""
        evicted: list[AgentSession] = []
        ttl = max(1, int(AGENT_SESSION_TTL_SECONDS))
        expired = [
            user_id
            for user_id, session in self._sessions.items()
            if not session.run_lock.locked()
            and now - session.last_accessed_at >= ttl
        ]
        for user_id in expired:
            session = self._sessions.pop(user_id, None)
            if session is not None:
                evicted.append(session)

        limit = max(1, int(AGENT_SESSION_MAX_ENTRIES))
        if incoming_user_id in self._sessions:
            return evicted
        candidates = sorted(
            (session.last_accessed_at, user_id)
            for user_id, session in self._sessions.items()
            if not session.run_lock.locked()
        )
        while len(self._sessions) >= limit and candidates:
            _, user_id = candidates.pop(0)
            session = self._sessions.pop(user_id, None)
            if session is not None:
                evicted.append(session)
        return evicted

    async def _ensure_resources(self):
        """初始化所有用户共享的 PostgreSQL Store / Checkpointer。"""
        if self._resources_ready:
            return

        if self._resources_lock is None:
            self._resources_lock = asyncio.Lock()

        async with self._resources_lock:
            if self._resources_ready:
                return
            await asyncio.to_thread(self._initialize_resources_sync)
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            from ..database import get_async_pg_pool

            self._async_pg_pool = await get_async_pg_pool()
            self._checkpointer = AsyncPostgresSaver(self._async_pg_pool)
            await self._checkpointer.setup()
            self._resources_ready = True

    def _initialize_resources_sync(self):
        """阻塞式资源初始化，调用方须放在线程池中。"""
        web_logger.info("Initializing shared Agent resources...")
        try:
            from langgraph.store.postgres import PostgresStore

            from ..database import (
                get_pg_pool,
                setup_database,
                setup_memory_search_schema,
            )

            setup_database()
            self._pg_pool = get_pg_pool()
            self._store = PostgresStore(self._pg_pool)
            self._store.setup()
            setup_memory_search_schema()
            self._app_repository = AppRepository()
            self._write_audit_repository = WriteAuditRepository()
            self._runtime_state_repository = RuntimeStateRepository()
            web_logger.info("Shared Agent resources initialized")
        except Exception as e:
            web_logger.error(f"Failed to initialize shared Agent resources: {e}")
            raise

    async def initialize(self, user_id: str | None = None, username: str = "用户"):
        """兼容旧调用：初始化共享资源，可选地预创建一个用户会话。"""
        await self._ensure_resources()
        if user_id is not None:
            await self.get_session(user_id, username)

    async def shutdown(self) -> None:
        """Close both PostgreSQL pools and discard agents bound to them."""
        from ..database import close_async_pg_pool, close_pg_pool

        sessions = list(self._sessions.values())
        if self._runtime_state_repository is not None:
            await asyncio.gather(
                *(
                    asyncio.to_thread(
                        self._runtime_state_repository.release,
                        session.ownership_lease,
                    )
                    for session in sessions
                ),
                return_exceptions=True,
            )
        self._sessions.clear()
        self.agent = None
        self._checkpointer = None
        self._store = None
        self._app_repository = None
        self._write_audit_repository = None
        self._runtime_state_repository = None
        self._pg_pool = None
        self._async_pg_pool = None
        self._resources_ready = False
        await close_async_pg_pool()
        await asyncio.to_thread(close_pg_pool)

    async def get_session(
        self,
        user_id: str,
        username: str = "用户",
        *,
        access_token: str = "",
        roles: frozenset[str] | None = None,
        permissions: frozenset[str] | None = None,
        authz_version: int = 1,
    ) -> AgentSession:
        """获取用户独享的 Agent 会话，避免不同用户共享 Sandbox/中间件状态。"""
        await self._ensure_resources()

        normalized_roles = frozenset(roles or ())
        normalized_permissions = frozenset(permissions or ())
        fingerprint = self._capability_fingerprint(
            user_id,
            username,
            normalized_roles,
            normalized_permissions,
            authz_version,
        )
        now = time.monotonic()

        if self._runtime_state_repository is None:
            raise RuntimeError("Runtime state repository is not initialized")
        ownership = await asyncio.to_thread(
            self._runtime_state_repository.acquire_session,
            user_id,
            owner_id=self.instance_id,
            ttl_seconds=AGENT_SESSION_TTL_SECONDS,
            metadata={
                "username": username,
                "authz_version": int(authz_version),
                "capability_fingerprint": list(fingerprint),
            },
        )
        if ownership is None:
            raise RuntimeLeaseConflict("该用户的 Agent 正在另一个实例执行，请稍后重试")

        if self._sessions_lock is None:
            self._sessions_lock = asyncio.Lock()
        async with self._sessions_lock:
            evicted = self._prune_sessions_locked(now, incoming_user_id=user_id)
            existing = self._sessions.get(user_id)
            if existing is not None and existing.capability_fingerprint == fingerprint:
                existing.last_accessed_at = now
                existing.ownership_lease = ownership
                selected = existing
            else:
                selected = None
            if existing is not None:
                if selected is None:
                    self._sessions.pop(user_id, None)
            build_lock = self._session_build_locks.setdefault(user_id, asyncio.Lock())

        for stale in evicted:
            # acquire_session() already renewed ownership for the incoming user.
            # Same-owner renewals intentionally preserve the token so an active
            # heartbeat is not invalidated; releasing the expired local cache's
            # identical token here would therefore delete the renewed row.
            if stale.user_id != user_id:
                await asyncio.to_thread(
                    self._runtime_state_repository.release, stale.ownership_lease
                )
        if selected is not None:
            return selected

        async with build_lock:
            async with self._sessions_lock:
                existing = self._sessions.get(user_id)
                if existing is not None and existing.capability_fingerprint == fingerprint:
                    existing.last_accessed_at = time.monotonic()
                    existing.ownership_lease = ownership
                    return existing

            try:
                agent, warm_memory_middleware, user_context = await asyncio.to_thread(
                    self._build_agent_for_user, user_id, username, access_token,
                    normalized_roles, normalized_permissions, authz_version
                )
            except Exception:
                async with self._sessions_lock:
                    self._session_build_locks.pop(user_id, None)
                raise
            created_at = time.monotonic()
            session = AgentSession(
                user_id=user_id,
                username=username,
                roles=normalized_roles,
                permissions=normalized_permissions,
                authz_version=authz_version,
                capability_fingerprint=fingerprint,
                agent=agent,
                run_lock=asyncio.Lock(),
                warm_memory_middleware=warm_memory_middleware,
                user_context=user_context,
                created_at=created_at,
                last_accessed_at=created_at,
                ownership_lease=ownership,
            )
            async with self._sessions_lock:
                self._sessions[user_id] = session
                self._session_build_locks.pop(user_id, None)
                # 兼容仍读取该字段的调试脚本。
                if user_id == "default_user":
                    self.agent = agent
            web_logger.info(f"Agent session ready for user: {user_id}")
            return session

    def _build_agent_for_user(
        self, user_id: str, username: str, access_token: str,
        roles: frozenset[str], permissions: frozenset[str], authz_version: int
    ):
        """在线程池中构建 Agent；其中包含 Docker/PostgreSQL 同步 I/O。"""
        from ..agent.main_agent import create_main_agent
        from ..agent.middlewares.warm_memory import WarmMemoryMiddleware

        context = ProcurementContext(
            user_id=user_id,
            username=username,
            roles=sorted(roles),
            permissions=sorted(permissions),
            authz_version=authz_version,
        )
        warm_memory_middleware = WarmMemoryMiddleware(
            store=self._store,
            user_id=user_id,
            user_context=context,
        )
        agent = create_main_agent(
            user_context=context,
            checkpointer=self._checkpointer,
            store=self._store,
            write_audit_repository=self._write_audit_repository,
            warm_memory_middleware=warm_memory_middleware,
            mcp_auth_token=access_token,
            permissions=permissions if access_token else None,
        )
        return agent, warm_memory_middleware, context

    @property
    def store(self):
        """供请求级工具上下文读取的共享 Store。"""
        return self._store

    @property
    def write_audit_repository(self) -> WriteAuditRepository:
        if self._write_audit_repository is None:
            raise RuntimeError("Agent resources are not initialized")
        return self._write_audit_repository

    @property
    def runtime_state_repository(self) -> RuntimeStateRepository:
        if self._runtime_state_repository is None:
            raise RuntimeError("Agent resources are not initialized")
        return self._runtime_state_repository

    def create_config(self, thread_id: str, user_id: str = "default_user") -> dict:
        """创建 LangGraph 配置并附带服务端生成的请求级采购上下文。"""
        session = self._sessions.get(user_id)
        context = (
            session.user_context
            if session is not None
            else ProcurementContext(user_id=user_id)
        )
        return {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
                PROCUREMENT_CONTEXT_CONFIG_KEY: context.model_dump(mode="json"),
            }
        }

    def generate_thread_id(self) -> str:
        """生成新的会话线程ID"""
        return str(uuid.uuid4())

    async def save_display_messages(self, thread_id: str, messages: list):
        """保存前端展示消息。"""
        await self._ensure_resources()
        await asyncio.to_thread(
            self._app_repository.save_display_messages, thread_id, messages
        )

    async def get_display_messages(self, thread_id: str) -> list:
        """获取前端展示消息"""
        await self._ensure_resources()
        return await asyncio.to_thread(
            self._app_repository.get_display_messages, thread_id
        )

    async def save_conversation(self, thread_id: str, user_id: str, title: str = "新对话"):
        """保存/更新会话记录"""
        await self._ensure_resources()
        await asyncio.to_thread(
            self._app_repository.save_conversation,
            thread_id,
            user_id,
            title,
        )

    async def get_conversations(self, user_id: str) -> list:
        """获取用户的会话列表"""
        await self._ensure_resources()
        return await asyncio.to_thread(
            self._app_repository.get_conversations, user_id
        )

    async def get_conversation_user_id(self, thread_id: str) -> str | None:
        """查询会话归属，供 resume/state 选择正确的用户 Agent。"""
        await self._ensure_resources()
        return await asyncio.to_thread(
            self._app_repository.get_conversation_user_id, thread_id
        )

    async def delete_conversation(self, thread_id: str):
        """删除会话"""
        await self._ensure_resources()
        await asyncio.to_thread(self._app_repository.delete_conversation, thread_id)

    async def save_harness_trace(self, thread_id: str, trace: list):
        """保存 Harness 阶段流转 trace（可观测/审计）。

        记录 Planning → Executing → Review → Result 各阶段的流转时间线，
        以及评审器的结构化判定结果，支持事后审计"哪一步卡住了"。
        """
        await self._ensure_resources()
        await asyncio.to_thread(
            self._app_repository.save_harness_trace, thread_id, trace
        )

    async def get_harness_trace(self, thread_id: str) -> list:
        """读取已持久化的 Harness 阶段与评审 Trace。"""
        await self._ensure_resources()
        return await asyncio.to_thread(
            self._app_repository.get_harness_trace, thread_id
        )


# 全局单例
agent_loader = AgentLoader()
