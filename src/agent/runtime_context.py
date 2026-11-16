"""每个流式 Agent 请求的轻量运行时上下文。

LangChain 工具实例在 Agent 构建时创建，不能把特定用户的 Store 或用户 ID
闭包进全局工具对象；ContextVar 让同一个工具在并发请求中仍能读取自己的上下文。
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, FrozenSet

_current_user_id: ContextVar[str] = ContextVar(
    "erp_agent_current_user_id", default="default_user"
)
_current_store: ContextVar[Any | None] = ContextVar(
    "erp_agent_current_store", default=None
)
_current_access_token: ContextVar[str] = ContextVar(
    "erp_agent_current_access_token", default=""
)
_current_permissions: ContextVar[FrozenSet[str] | None] = ContextVar(
    "erp_agent_current_permissions", default=None
)


def bind_runtime(
    user_id: str,
    store: Any | None,
    *,
    access_token: str = "",
    permissions: FrozenSet[str] | None = None,
) -> tuple[Token[str], Token[Any | None], Token[str], Token[FrozenSet[str] | None]]:
    """绑定请求身份、Store 与短期凭据。

    Agent 和工具对象可以跨 access-token 刷新复用；Bearer token 只在本次请求的
    ContextVar 中存在，并在 MCP 工具真正执行时注入，避免把某枚 JWT 固化到会话。
    ``permissions=None`` 只用于显式的本地无认证模式，空集合表示已认证但无权限。
    """
    return (
        _current_user_id.set(user_id),
        _current_store.set(store),
        _current_access_token.set(access_token or ""),
        _current_permissions.set(permissions),
    )


def reset_runtime(
    tokens: tuple[
        Token[str], Token[Any | None], Token[str], Token[FrozenSet[str] | None]
    ]
) -> None:
    """复位 ``bind_runtime`` 产生的上下文。"""
    user_token, store_token, access_token, permissions_token = tokens
    _current_user_id.reset(user_token)
    _current_store.reset(store_token)
    _current_access_token.reset(access_token)
    _current_permissions.reset(permissions_token)


def get_current_user_id() -> str:
    return _current_user_id.get()


def get_current_store() -> Any | None:
    return _current_store.get()


def get_current_access_token() -> str:
    """返回当前 HTTP 请求的 JWT；不得写入日志、Store 或 AgentSession。"""
    return _current_access_token.get()


def get_current_permissions() -> FrozenSet[str] | None:
    return _current_permissions.get()


def has_runtime_permission(permission: str) -> bool:
    """工具级纵深校验；本地无认证模式（None）保持开发兼容。"""
    permissions = get_current_permissions()
    return permissions is None or permission in permissions
