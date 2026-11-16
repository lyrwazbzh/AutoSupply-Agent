"""PostgreSQL-backed ownership and run leases for horizontally safe Agents."""

from __future__ import annotations

import socket
import uuid
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from .database import get_pg_pool, setup_database


class RuntimeLeaseConflict(RuntimeError):
    """Another backend instance currently owns the requested runtime resource."""


@dataclass(frozen=True)
class LeaseHandle:
    resource_type: str
    resource_key: str
    owner_id: str
    token: str
    expires_at: Any
    version: int


def new_instance_id(component: str = "backend") -> str:
    return f"{component}:{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


class RuntimeStateRepository:
    """The database is authoritative; in-process locks are only local optimisations."""

    def __init__(self) -> None:
        setup_database()
        self.pool = get_pg_pool()

    @staticmethod
    def _handle(row: dict[str, Any] | None) -> LeaseHandle | None:
        if not row:
            return None
        return LeaseHandle(
            resource_type=str(row["resource_type"]),
            resource_key=str(row["resource_key"]),
            owner_id=str(row["owner_id"]),
            token=str(row["lease_token"]),
            expires_at=row["lease_expires_at"],
            version=int(row["version"]),
        )

    def acquire_session(
        self,
        user_id: str,
        *,
        owner_id: str,
        ttl_seconds: int,
        metadata: dict[str, Any] | None = None,
    ) -> LeaseHandle | None:
        """Claim AgentSession ownership unless another instance has an active run.

        Idle sessions can move between replicas immediately. During an active run,
        ownership is pinned to the replica holding ``agent_run``.
        """
        token = uuid.uuid4().hex
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"agent-session:{user_id}",),
                )
                cur.execute(
                    """
                    SELECT owner_id FROM app.runtime_leases
                    WHERE resource_type = 'agent_run' AND resource_key = %s
                      AND lease_expires_at > now()
                    FOR UPDATE
                    """,
                    (user_id,),
                )
                active_run = cur.fetchone()
                if active_run and str(active_run["owner_id"]) != owner_id:
                    return None
                cur.execute(
                    """
                    INSERT INTO app.runtime_leases(
                        resource_type, resource_key, owner_id, lease_token,
                        lease_expires_at, metadata
                    ) VALUES ('agent_session', %s, %s, %s,
                              now() + (%s * interval '1 second'), %s)
                    ON CONFLICT (resource_type, resource_key) DO UPDATE SET
                        owner_id = EXCLUDED.owner_id,
                        lease_token = CASE
                            WHEN app.runtime_leases.owner_id = EXCLUDED.owner_id
                            THEN app.runtime_leases.lease_token
                            ELSE EXCLUDED.lease_token
                        END,
                        lease_expires_at = EXCLUDED.lease_expires_at,
                        metadata = EXCLUDED.metadata,
                        version = app.runtime_leases.version + 1,
                        updated_at = now()
                    RETURNING *
                    """,
                    (
                        user_id,
                        owner_id,
                        token,
                        max(5, int(ttl_seconds)),
                        Jsonb(metadata or {}),
                    ),
                )
                return self._handle(dict(cur.fetchone()))

    def acquire_run(
        self,
        user_id: str,
        *,
        owner_id: str,
        ttl_seconds: int,
        metadata: dict[str, Any] | None = None,
    ) -> LeaseHandle | None:
        """Acquire the cross-replica per-user execution lease.

        The caller must own the externalized AgentSession. An unexpired run held by
        another replica is never stolen.
        """
        token = uuid.uuid4().hex
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"agent-session:{user_id}",),
                )
                cur.execute(
                    """
                    SELECT owner_id FROM app.runtime_leases
                    WHERE resource_type = 'agent_session' AND resource_key = %s
                      AND lease_expires_at > now()
                    FOR UPDATE
                    """,
                    (user_id,),
                )
                session = cur.fetchone()
                if not session or str(session["owner_id"]) != owner_id:
                    return None
                cur.execute(
                    """
                    INSERT INTO app.runtime_leases(
                        resource_type, resource_key, owner_id, lease_token,
                        lease_expires_at, metadata
                    ) VALUES ('agent_run', %s, %s, %s,
                              now() + (%s * interval '1 second'), %s)
                    ON CONFLICT (resource_type, resource_key) DO UPDATE SET
                        owner_id = EXCLUDED.owner_id,
                        lease_token = EXCLUDED.lease_token,
                        lease_expires_at = EXCLUDED.lease_expires_at,
                        metadata = EXCLUDED.metadata,
                        version = app.runtime_leases.version + 1,
                        updated_at = now()
                    WHERE app.runtime_leases.lease_expires_at <= now()
                    RETURNING *
                    """,
                    (
                        user_id,
                        owner_id,
                        token,
                        max(5, int(ttl_seconds)),
                        Jsonb(metadata or {}),
                    ),
                )
                row = cur.fetchone()
                return self._handle(dict(row)) if row else None

    def acquire_sandbox_run(
        self,
        user_id: str,
        *,
        owner_id: str,
        ttl_seconds: int,
    ) -> LeaseHandle | None:
        """Pin a sandbox allocation to the instance that owns the Agent run."""
        token = uuid.uuid4().hex
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT owner_id FROM app.runtime_leases
                    WHERE resource_type = 'agent_run' AND resource_key = %s
                      AND lease_expires_at > now()
                    FOR UPDATE
                    """,
                    (user_id,),
                )
                run = cur.fetchone()
                if not run or str(run["owner_id"]) != owner_id:
                    return None
                cur.execute(
                    """
                    INSERT INTO app.runtime_leases(
                        resource_type, resource_key, owner_id, lease_token,
                        lease_expires_at
                    ) VALUES ('sandbox_run', %s, %s, %s,
                              now() + (%s * interval '1 second'))
                    ON CONFLICT (resource_type, resource_key) DO UPDATE SET
                        owner_id = EXCLUDED.owner_id,
                        lease_token = EXCLUDED.lease_token,
                        lease_expires_at = EXCLUDED.lease_expires_at,
                        version = app.runtime_leases.version + 1,
                        updated_at = now()
                    WHERE app.runtime_leases.lease_expires_at <= now()
                    RETURNING *
                    """,
                    (user_id, owner_id, token, max(5, int(ttl_seconds))),
                )
                row = cur.fetchone()
                return self._handle(dict(row)) if row else None

    def renew(self, handle: LeaseHandle, *, ttl_seconds: int) -> LeaseHandle | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE app.runtime_leases
                SET lease_expires_at = now() + (%s * interval '1 second'),
                    version = version + 1, updated_at = now()
                WHERE resource_type = %s AND resource_key = %s
                  AND owner_id = %s AND lease_token = %s
                  AND lease_expires_at > now()
                RETURNING *
                """,
                (
                    max(5, int(ttl_seconds)),
                    handle.resource_type,
                    handle.resource_key,
                    handle.owner_id,
                    handle.token,
                ),
            )
            row = cur.fetchone()
            return self._handle(dict(row)) if row else None

    def release(self, handle: LeaseHandle) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM app.runtime_leases
                WHERE resource_type = %s AND resource_key = %s
                  AND owner_id = %s AND lease_token = %s
                """,
                (
                    handle.resource_type,
                    handle.resource_key,
                    handle.owner_id,
                    handle.token,
                ),
            )
            return cur.rowcount == 1

    def has_active_lease(self, resource_type: str, resource_key: str) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM app.runtime_leases
                WHERE resource_type = %s AND resource_key = %s
                  AND lease_expires_at > now()
                """,
                (resource_type, resource_key),
            )
            return cur.fetchone() is not None
