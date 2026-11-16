import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from src.api_view import auth


class JwtAuthTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_key = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        cls.public_key = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def token(self, **overrides):
        now = int(time.time())
        claims = {
            "iss": "java-erp",
            "aud": ["erp-api", "assistant-api", "mcp"],
            "sub": "usr_123",
            "iat": now,
            "exp": now + 300,
            "username": "buyer",
            "display_name": "采购员",
            "roles": ["PURCHASER"],
            "permissions": ["assistant:use", "erp:order:create"],
            "authz_version": 8,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256")

    async def test_valid_token_builds_principal_without_exposing_raw_token(self):
        raw = self.token()
        with patch.object(auth, "_public_key", return_value=self.public_key), \
             patch.object(auth, "JWT_ACTIVE_CHECK_ENABLED", False):
            principal = await auth._decode_bearer(f"Bearer {raw}")
        self.assertEqual("usr_123", principal.subject)
        self.assertEqual(frozenset({"PURCHASER"}), principal.roles)
        self.assertIn("erp:order:create", principal.permissions)
        self.assertEqual(8, principal.authz_version)
        self.assertNotIn(raw, repr(principal))

    async def test_wrong_audience_is_rejected(self):
        raw = self.token(aud=["some-other-service"])
        with patch.object(auth, "_public_key", return_value=self.public_key), \
             patch.object(auth, "JWT_ACTIVE_CHECK_ENABLED", False):
            with self.assertRaises(HTTPException) as raised:
                await auth._decode_bearer(f"Bearer {raw}")
        self.assertEqual(401, raised.exception.status_code)

    async def test_missing_bearer_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            await auth._decode_bearer(None)
        self.assertEqual(401, raised.exception.status_code)

    def test_interface_permission_is_enforced_in_jwt_mode(self):
        principal = auth.AuthenticatedPrincipal(
            subject="usr_123",
            username="viewer",
            display_name="查看者",
            permissions=frozenset({"assistant:use"}),
        )
        context_token = auth._current_principal.set(principal)
        try:
            with patch.object(auth, "AUTH_MODE", "jwt"):
                auth.assert_permission("assistant:use")
                with self.assertRaises(HTTPException) as raised:
                    auth.assert_permission("system:user:manage")
            self.assertEqual(403, raised.exception.status_code)
        finally:
            auth._current_principal.reset(context_token)

    def test_interface_permission_keeps_explicit_dev_mode(self):
        with patch.object(auth, "AUTH_MODE", "none"):
            auth.assert_permission("assistant:use")


if __name__ == "__main__":
    unittest.main()
