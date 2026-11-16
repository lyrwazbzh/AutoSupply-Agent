"""JWT resource-server authentication for the MCP gateway."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import jwt
from fastmcp.server.auth import AccessToken, TokenVerifier


@lru_cache(maxsize=2)
def _public_key(path: str) -> str:
    return Path(path).read_text(encoding="ascii")


class ERPJwtVerifier(TokenVerifier):
    def __init__(self) -> None:
        super().__init__()
        self.public_key_path = os.getenv("JWT_PUBLIC_KEY_PATH", "").strip()
        self.issuer = os.getenv("JWT_ISSUER", "java-erp").strip()
        self.audience = os.getenv("MCP_JWT_AUDIENCE", "mcp").strip()
        if not self.public_key_path:
            raise RuntimeError("JWT_PUBLIC_KEY_PATH is required when MCP_AUTH_ENABLED=true")

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                _public_key(self.public_key_path),
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["sub", "exp", "iat", "iss", "aud"]},
            )
        except (jwt.PyJWTError, OSError):
            return None
        permissions = [str(value) for value in claims.get("permissions") or ()]
        return AccessToken(
            token=token,
            client_id=str(claims["sub"]),
            subject=str(claims["sub"]),
            scopes=permissions,
            expires_at=int(claims["exp"]),
            claims=claims,
        )

