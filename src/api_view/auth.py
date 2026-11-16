"""
身份解析

容器部署使用 Java ERP 签发的 RS256 JWT。backend 本地验签后，再向 Java ERP
确认账号状态和 ``authz_version``，使停用和改权立即生效。

生产只接受 JWT 身份；``AUTH_MODE=none`` 仅用于本机离线开发。
"""
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
import jwt
from fastapi import Depends, Header, HTTPException

from ..agent.config import (
    AUTH_MODE,
    ERP_BASE_URL,
    JWT_ACTIVE_CHECK_ENABLED,
    JWT_AUDIENCE,
    JWT_ISSUER,
    JWT_PUBLIC_KEY_PATH,
)
from ..agent.log_utils import web_logger

DEFAULT_USER_ID = "default_user"


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    subject: str
    username: str
    display_name: str
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    authz_version: int = 1
    access_token: str = field(default="", repr=False)


_current_principal: ContextVar[AuthenticatedPrincipal | None] = ContextVar(
    "erp_authenticated_principal", default=None
)


def get_request_principal() -> AuthenticatedPrincipal | None:
    return _current_principal.get()


@lru_cache(maxsize=4)
def _public_key(path: str) -> str:
    if not path:
        raise HTTPException(status_code=503, detail="JWT 公钥未配置")
    try:
        return Path(path).read_text(encoding="ascii")
    except OSError as exc:
        web_logger.error("Cannot read JWT public key %s: %s", path, exc)
        raise HTTPException(status_code=503, detail="JWT 验证配置不可用") from exc


async def _decode_bearer(authorization: str | None) -> AuthenticatedPrincipal:
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    raw = authorization[7:].strip()
    try:
        claims = jwt.decode(
            raw,
            _public_key(JWT_PUBLIC_KEY_PATH),
            algorithms=["RS256"],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        web_logger.info("Rejected invalid JWT: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="登录已过期或 Token 无效") from exc
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise HTTPException(status_code=401, detail="Token 缺少用户主体")
    principal = AuthenticatedPrincipal(
        subject=subject,
        username=str(claims.get("username") or subject),
        display_name=str(claims.get("display_name") or claims.get("username") or subject),
        roles=frozenset(str(v) for v in claims.get("roles") or ()),
        permissions=frozenset(str(v) for v in claims.get("permissions") or ()),
        authz_version=int(claims.get("authz_version") or 1),
        access_token=raw,
    )
    # Java ERP 持有账号状态与 authz_version 的唯一真值。只做离线验签会让已经
    # 停用或改权的令牌在 15 分钟内仍能访问助手，因此每个入口请求向签发方确认一次。
    if JWT_ACTIVE_CHECK_ENABLED:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{ERP_BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {raw}"},
                )
        except httpx.HTTPError as exc:
            web_logger.warning("JWT active check unavailable: %s", exc)
            raise HTTPException(status_code=503, detail="身份服务暂时不可用") from exc
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="登录状态或权限已经变更")
    return principal


async def current_user_id(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Optional[str]:
    """Return the JWT subject, or ``None`` in explicit local dev mode."""
    if AUTH_MODE == "jwt":
        principal = await _decode_bearer(authorization)
        _current_principal.set(principal)
        return principal.subject
    if AUTH_MODE == "none":
        _current_principal.set(None)
        return None
    raise HTTPException(status_code=503, detail="AUTH_MODE 配置无效，只允许 jwt 或 none")


def require_permission(permission: str):
    async def dependency(_: str | None = Depends(current_user_id)) -> AuthenticatedPrincipal:
        principal = get_request_principal()
        if principal is None:
            raise HTTPException(status_code=401, detail="未认证")
        if permission not in principal.permissions:
            raise HTTPException(status_code=403, detail="权限不足")
        return principal
    return dependency


def assert_permission(*permissions: str) -> None:
    """Enforce JWT permissions while preserving explicit local dev mode."""
    if AUTH_MODE != "jwt":
        return
    principal = get_request_principal()
    if principal is None:
        raise HTTPException(status_code=401, detail="未认证")
    if not any(permission in principal.permissions for permission in permissions):
        raise HTTPException(status_code=403, detail="权限不足")


def resolve_user_id(authenticated: Optional[str], requested: Optional[str]) -> str:
    """决定本次请求用哪个 user_id。

    认证身份优先，且会显式记录被丢弃的客户端取值 —— 如果日志里出现这行，
    说明有客户端在试图指定别人的身份。
    """
    if authenticated:
        if requested and requested != authenticated:
            web_logger.info(
                f"Ignoring client-supplied user_id {requested!r}, "
                f"using authenticated identity {authenticated!r}"
            )
        return authenticated
    return requested or DEFAULT_USER_ID


def assert_thread_owner(thread_id: str, owner: Optional[str], user_id: Optional[str]) -> None:
    """校验会话归属。

    ``user_id`` 为 None 表示没开认证（AUTH_MODE=none），此时不做校验以保持
    本机开发行为不变。开启认证后 ``owner`` 为空（会话记录不存在）也一律拒绝 ——
    放行会变成"随便报一个 thread_id 就能读"。
    """
    if user_id is None:
        return
    if not owner or owner != user_id:
        web_logger.warning(
            f"Denied cross-user access to thread {thread_id}: owner={owner!r}, requester={user_id!r}"
        )
        raise HTTPException(status_code=403, detail="该会话不属于当前用户")
