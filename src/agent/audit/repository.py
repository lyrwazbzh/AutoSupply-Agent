"""PostgreSQL repository for append-only write audit events and durable jobs."""

from __future__ import annotations

import socket
import uuid
from typing import Any

from psycopg.types.json import Jsonb

from ...database import get_pg_pool, setup_database
from ..approval import approval_policy_registry
from .payloads import payload_hash, redact
from .registry import WriteToolSpec


class WriteAuditRepository:
    def __init__(self) -> None:
        setup_database()
        self.pool = get_pg_pool()
        self.worker_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"

    @staticmethod
    def operation_id(thread_id: str, tool_call_id: str) -> str:
        stable = f"{thread_id or 'no-thread'}:{tool_call_id or 'no-call'}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"erp-write:{stable}"))

    def start_operation(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        tool_call_id: str,
        thread_id: str,
        user_id: str,
        agent_name: str,
        tool_name: str,
        spec: WriteToolSpec,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        safe_payload = redact(payload)
        digest = payload_hash(payload)
        status = "PENDING_APPROVAL" if spec.requires_approval else "CREATED"
        policy = approval_policy_registry.get(tool_name)
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit.write_operations(
                        operation_id, idempotency_key, tool_call_id, thread_id,
                        user_id, agent_name, tool_name, domain, action,
                        approval_required, policy_id, policy_version,
                        payload_redacted, payload_hash, status,
                        next_reconcile_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        now() + interval '60 seconds'
                    )
                    ON CONFLICT (operation_id) DO NOTHING
                    """,
                    (
                        operation_id,
                        idempotency_key,
                        tool_call_id,
                        thread_id,
                        user_id,
                        agent_name,
                        tool_name,
                        spec.domain,
                        spec.action,
                        spec.requires_approval,
                        policy.policy_id if policy else None,
                        policy.version if policy else None,
                        Jsonb(safe_payload),
                        digest,
                        status,
                    ),
                )
                cur.execute(
                    "SELECT * FROM audit.write_operations WHERE operation_id = %s FOR UPDATE",
                    (operation_id,),
                )
                row = dict(cur.fetchone())
                if row["payload_hash"] != digest or row["tool_name"] != tool_name:
                    raise ValueError(
                        f"operation_id={operation_id} 已绑定不同写载荷，拒绝执行"
                    )
                self._insert_event(
                    cur,
                    operation=row,
                    event_type="requested",
                    event_key="requested",
                    detail={"payload_hash": digest},
                )
                if spec.requires_approval:
                    cur.execute(
                        """
                        INSERT INTO audit.approval_tasks(
                            task_id, operation_id, requester_id, status
                        ) VALUES (%s, %s, %s, 'PENDING')
                        ON CONFLICT (operation_id) DO NOTHING
                        """,
                        (f"approval:{operation_id}", operation_id, user_id),
                    )
                cur.execute(
                    """
                    INSERT INTO audit.reconcile_jobs(operation_id, job_status, next_run_at)
                    VALUES (%s, 'PENDING', now() + interval '60 seconds')
                    ON CONFLICT (operation_id) DO NOTHING
                    """,
                    (operation_id,),
                )
                return row

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM audit.write_operations WHERE operation_id = %s",
                (operation_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def mark_pending(self, operation_id: str) -> None:
        self._transition(
            operation_id,
            status="PENDING_APPROVAL",
            event_type="approval_pending",
            event_key="approval_pending",
        )

    def list_pending_approvals(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return the independent maker-checker queue without conversation data."""
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.task_id, t.operation_id, t.requester_id,
                       t.status AS approval_status, t.created_at,
                       o.tool_name, o.domain, o.action, o.payload_redacted,
                       o.payload_hash, o.policy_id, o.policy_version
                FROM audit.approval_tasks t
                JOIN audit.write_operations o USING (operation_id)
                WHERE t.status = 'PENDING'
                  AND o.status = 'PENDING_APPROVAL'
                ORDER BY t.created_at, t.task_id
                LIMIT %s
                """,
                (max(1, min(int(limit), 500)),),
            )
            return [dict(row) for row in cur.fetchall()]

    def decide_approval(
        self,
        operation_id: str,
        *,
        decision: str,
        actor_id: str,
        note: str = "",
        expected_payload_hash: str = "",
    ) -> dict[str, Any]:
        """Decide exactly one task by operation_id and enforce maker != checker."""
        normalized = (decision or "").strip().lower()
        if normalized not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        actor = (actor_id or "").strip()
        if not actor:
            raise ValueError("actor_id is required")

        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.task_id, t.operation_id, t.requester_id,
                           t.status AS task_status, t.decision_note,
                           o.thread_id, o.user_id, o.agent_name, o.tool_name,
                           o.payload_hash, o.status AS operation_status
                    FROM audit.approval_tasks t
                    JOIN audit.write_operations o USING (operation_id)
                    WHERE t.operation_id = %s
                    FOR UPDATE OF t, o
                    """,
                    (operation_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(f"unknown approval operation: {operation_id}")
                operation = dict(row)
                if actor == str(operation["requester_id"]):
                    raise PermissionError("申请人不能审批自己的写操作")
                if operation["task_status"] != "PENDING" or operation["operation_status"] != "PENDING_APPROVAL":
                    raise ValueError("该审批任务已经处理或写操作不再等待审批")
                if expected_payload_hash and expected_payload_hash != str(operation["payload_hash"]):
                    raise ValueError("审批载荷已变化，必须重新检查后再审批")

                approved = normalized == "approve"
                target = "APPROVED" if approved else "REJECTED"
                cur.execute(
                    """
                    UPDATE audit.approval_tasks
                    SET status = %s, decided_by = %s, decision_note = %s,
                        decided_at = now(), updated_at = now()
                    WHERE operation_id = %s
                    """,
                    (target, actor, (note or "")[:2000], operation_id),
                )
                self._update_operation(cur, operation_id, status=target)
                self._insert_event(
                    cur,
                    operation=operation,
                    event_type="approved" if approved else "rejected",
                    event_key="approved" if approved else "rejected",
                    actor_id=actor,
                    detail={"decision": normalized, "note": (note or "")[:2000]},
                )
                if not approved:
                    cur.execute(
                        """
                        UPDATE audit.reconcile_jobs
                        SET job_status = 'DONE', locked_by = NULL,
                            locked_at = NULL, updated_at = now()
                        WHERE operation_id = %s
                        """,
                        (operation_id,),
                    )
                cur.execute(
                    """
                    SELECT t.*, o.tool_name, o.payload_hash, o.status AS operation_status
                    FROM audit.approval_tasks t
                    JOIN audit.write_operations o USING (operation_id)
                    WHERE t.operation_id = %s
                    """,
                    (operation_id,),
                )
                return dict(cur.fetchone())

    def approval_decisions(
        self,
        operation_ids: list[str],
        *,
        thread_id: str,
        requester_id: str,
    ) -> list[dict[str, str]]:
        """Resolve checkpoint actions from durable decisions in checkpoint order."""
        if not operation_ids or len(operation_ids) != len(set(operation_ids)):
            raise ValueError("待恢复操作必须包含唯一 operation_id")
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.operation_id, t.status, t.decision_note
                FROM audit.approval_tasks t
                JOIN audit.write_operations o USING (operation_id)
                WHERE t.operation_id = ANY(%s)
                  AND o.thread_id = %s AND o.user_id = %s
                """,
                (operation_ids, thread_id, requester_id),
            )
            rows = {str(row["operation_id"]): dict(row) for row in cur.fetchall()}
        missing = [operation_id for operation_id in operation_ids if operation_id not in rows]
        if missing:
            raise ValueError(f"审批任务不存在或不属于申请人: {missing[0]}")
        pending = [operation_id for operation_id in operation_ids if rows[operation_id]["status"] == "PENDING"]
        if pending:
            raise RuntimeError(f"写操作仍在等待独立审批: {pending[0]}")
        decisions: list[dict[str, str]] = []
        for operation_id in operation_ids:
            row = rows[operation_id]
            decision = "approve" if row["status"] == "APPROVED" else "reject"
            item = {"type": decision}
            if decision == "reject" and row.get("decision_note"):
                item["message"] = str(row["decision_note"])
            decisions.append(item)
        return decisions

    def mark_dispatching(self, operation_id: str) -> None:
        self._transition(
            operation_id,
            status="DISPATCHING",
            event_type="dispatch_started",
            event_key="dispatch_started",
            increment_attempt=True,
            next_reconcile_seconds=60,
        )

    def mark_blocked(self, operation_id: str, reason: str) -> None:
        self._transition(
            operation_id,
            status="FAILED",
            event_type="guard_blocked",
            event_key="guard_blocked",
            detail={"reason": reason[:2000]},
            error=reason,
            complete_job=True,
        )

    def mark_result(
        self,
        operation_id: str,
        *,
        success: bool,
        result: Any,
        error: str | None = None,
        erp_reference: str | None = None,
        unknown: bool = False,
    ) -> None:
        if unknown:
            status, event_type, complete = "UNKNOWN", "result_unknown", False
        elif success:
            status, event_type, complete = "SUCCEEDED", "succeeded", True
        else:
            status, event_type, complete = "FAILED", "failed", True
        safe_result = redact(result)
        digest = payload_hash(result)
        self._transition(
            operation_id,
            status=status,
            event_type=event_type,
            event_key=event_type,
            detail={"result": safe_result, "result_hash": digest, "error": error},
            error=error,
            result=safe_result,
            result_hash_value=digest,
            erp_reference=erp_reference,
            complete_job=complete,
            next_reconcile_seconds=30 if unknown else None,
        )

    def list_operations(
        self,
        *,
        user_id: str,
        thread_id: str | None = None,
        status: str | None = None,
        tool_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = %s"]
        params: list[Any] = [user_id]
        for column, value in (
            ("thread_id", thread_id),
            ("status", status),
            ("tool_name", tool_name),
        ):
            if value:
                clauses.append(f"{column} = %s")
                params.append(value)
        params.append(max(1, min(int(limit), 500)))
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM audit.write_operations
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT %s
                """,
                tuple(params),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_operation_with_events(
        self, operation_id: str, *, user_id: str | None = None
    ) -> dict[str, Any] | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            if user_id:
                cur.execute(
                    "SELECT * FROM audit.write_operations WHERE operation_id = %s AND user_id = %s",
                    (operation_id, user_id),
                )
            else:
                cur.execute(
                    "SELECT * FROM audit.write_operations WHERE operation_id = %s",
                    (operation_id,),
                )
            operation = cur.fetchone()
            if not operation:
                return None
            cur.execute(
                """
                SELECT * FROM audit.write_audit_events
                WHERE operation_id = %s ORDER BY created_at, event_id
                """,
                (operation_id,),
            )
            return {
                "operation": dict(operation),
                "events": [dict(row) for row in cur.fetchall()],
            }

    def lease_reconcile_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    """
                    WITH candidates AS (
                        SELECT j.operation_id
                        FROM audit.reconcile_jobs j
                        JOIN audit.write_operations o USING (operation_id)
                        WHERE (
                            (j.job_status = 'PENDING' AND j.next_run_at <= now())
                            OR
                            (j.job_status = 'RUNNING'
                             AND j.locked_at < now() - interval '5 minutes')
                          )
                          AND o.status IN ('DISPATCHING', 'UNKNOWN', 'RECONCILING')
                        ORDER BY j.next_run_at
                        FOR UPDATE OF j SKIP LOCKED
                        LIMIT %s
                    )
                    UPDATE audit.reconcile_jobs j
                    SET job_status = 'RUNNING', locked_by = %s, locked_at = now(),
                        attempt_count = j.attempt_count + 1, updated_at = now()
                    FROM candidates c
                    WHERE j.operation_id = c.operation_id
                    RETURNING j.operation_id, j.attempt_count
                    """,
                    (max(1, min(limit, 100)), self.worker_id),
                )
                leased = [dict(row) for row in cur.fetchall()]
                for item in leased:
                    cur.execute(
                        "SELECT * FROM audit.write_operations WHERE operation_id = %s",
                        (item["operation_id"],),
                    )
                    item["operation"] = dict(cur.fetchone())
                    self._update_operation(cur, item["operation_id"], status="RECONCILING")
                    self._insert_event(
                        cur,
                        operation=item["operation"],
                        event_type="reconcile_started",
                        event_key=f"reconcile_started:{item['attempt_count']}",
                        detail={"attempt": item["attempt_count"], "worker": self.worker_id},
                    )
                return leased

    def finish_reconcile(
        self,
        operation_id: str,
        *,
        outcome: str,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
        retry_seconds: int | None = None,
    ) -> None:
        allowed = {"RECONCILED_SUCCEEDED", "NOT_APPLIED", "MANUAL_REQUIRED", "UNKNOWN"}
        if outcome not in allowed:
            raise ValueError(f"invalid reconcile outcome: {outcome}")
        event_type = {
            "RECONCILED_SUCCEEDED": "reconcile_succeeded",
            "NOT_APPLIED": "reconcile_not_applied",
            "MANUAL_REQUIRED": "manual_required",
            "UNKNOWN": "reconcile_deferred",
        }[outcome]
        complete = outcome != "UNKNOWN"
        reconciled_result = (
            (detail or {}).get("result")
            if outcome == "RECONCILED_SUCCEEDED"
            else None
        )
        self._transition(
            operation_id,
            status=outcome,
            event_type=event_type,
            event_key=f"{event_type}:{uuid.uuid4().hex}",
            detail=detail,
            error=error,
            result=redact(reconciled_result) if reconciled_result is not None else None,
            result_hash_value=(
                payload_hash(reconciled_result)
                if reconciled_result is not None
                else None
            ),
            complete_job=complete,
            next_reconcile_seconds=retry_seconds,
            manual_job=outcome == "MANUAL_REQUIRED",
        )

    def list_manual_required(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """运维台：待人工处理的写操作队列。"""
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM audit.write_operations
                WHERE status = 'MANUAL_REQUIRED'
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (max(1, min(int(limit), 500)),),
            )
            return [dict(row) for row in cur.fetchall()]

    def resolve_manual(
        self,
        operation_id: str,
        *,
        resolution: str,
        actor_id: str,
        note: str = "",
    ) -> dict[str, Any]:
        """运维确认人工处理完毕并结案。

        resolution:
        - succeeded → MANUAL_RESOLVED_SUCCEEDED（视为已落账，可幂等回放结果）
        - not_applied → MANUAL_RESOLVED_NOT_APPLIED（允许用户新请求重试）
        - abandoned → MANUAL_RESOLVED_ABANDONED（结案，禁止静默重试）
        """
        mapping = {
            "succeeded": "MANUAL_RESOLVED_SUCCEEDED",
            "not_applied": "MANUAL_RESOLVED_NOT_APPLIED",
            "abandoned": "MANUAL_RESOLVED_ABANDONED",
        }
        status = mapping.get((resolution or "").strip().lower())
        if status is None:
            raise ValueError(
                "resolution must be one of: succeeded, not_applied, abandoned"
            )
        if not (actor_id or "").strip():
            raise ValueError("actor_id is required")

        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM audit.write_operations WHERE operation_id = %s FOR UPDATE",
                    (operation_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(f"unknown write operation: {operation_id}")
                operation = dict(row)
                if operation.get("status") != "MANUAL_REQUIRED":
                    raise ValueError(
                        f"operation status is {operation.get('status')}, "
                        "only MANUAL_REQUIRED can be resolved"
                    )
                self._update_operation(cur, operation_id, status=status)
                self._insert_event(
                    cur,
                    operation=operation,
                    event_type="manual_resolved",
                    event_key=f"manual_resolved:{uuid.uuid4().hex}",
                    actor_id=actor_id.strip(),
                    detail={
                        "resolution": resolution.strip().lower(),
                        "note": (note or "")[:2000],
                        "status": status,
                    },
                )
                cur.execute(
                    """
                    UPDATE audit.reconcile_jobs
                    SET job_status = 'DONE', locked_by = NULL, locked_at = NULL,
                        updated_at = now()
                    WHERE operation_id = %s
                    """,
                    (operation_id,),
                )
                cur.execute(
                    "SELECT * FROM audit.write_operations WHERE operation_id = %s",
                    (operation_id,),
                )
                return dict(cur.fetchone())

    def _transition(
        self,
        operation_id: str,
        *,
        status: str,
        event_type: str,
        event_key: str,
        actor_id: str | None = None,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
        result: Any = None,
        result_hash_value: str | None = None,
        erp_reference: str | None = None,
        increment_attempt: bool = False,
        complete_job: bool = False,
        manual_job: bool = False,
        next_reconcile_seconds: int | None = None,
    ) -> None:
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM audit.write_operations WHERE operation_id = %s FOR UPDATE",
                    (operation_id,),
                )
                operation = cur.fetchone()
                if not operation:
                    raise KeyError(f"unknown write operation: {operation_id}")
                operation = dict(operation)
                self._update_operation(
                    cur,
                    operation_id,
                    status=status,
                    error=error,
                    result=result,
                    result_hash_value=result_hash_value,
                    erp_reference=erp_reference,
                    increment_attempt=increment_attempt,
                    next_reconcile_seconds=next_reconcile_seconds,
                )
                self._insert_event(
                    cur,
                    operation=operation,
                    event_type=event_type,
                    event_key=event_key,
                    actor_id=actor_id,
                    detail=detail or {},
                )
                if complete_job:
                    cur.execute(
                        """
                        UPDATE audit.reconcile_jobs
                        SET job_status = 'DONE', locked_by = NULL, locked_at = NULL,
                            updated_at = now()
                        WHERE operation_id = %s
                        """,
                        (operation_id,),
                    )
                elif manual_job:
                    cur.execute(
                        """
                        UPDATE audit.reconcile_jobs
                        SET job_status = 'MANUAL_REQUIRED', last_error = %s,
                            locked_by = NULL, locked_at = NULL, updated_at = now()
                        WHERE operation_id = %s
                        """,
                        (error, operation_id),
                    )
                elif next_reconcile_seconds is not None:
                    cur.execute(
                        """
                        UPDATE audit.reconcile_jobs
                        SET job_status = 'PENDING', next_run_at = now() + (%s * interval '1 second'),
                            last_error = %s, locked_by = NULL, locked_at = NULL,
                            updated_at = now()
                        WHERE operation_id = %s
                        """,
                        (next_reconcile_seconds, error, operation_id),
                    )

    @staticmethod
    def _update_operation(
        cur,
        operation_id: str,
        *,
        status: str,
        error: str | None = None,
        result: Any = None,
        result_hash_value: str | None = None,
        erp_reference: str | None = None,
        increment_attempt: bool = False,
        next_reconcile_seconds: int | None = None,
    ) -> None:
        cur.execute(
            """
            UPDATE audit.write_operations
            SET status = %s,
                last_error = COALESCE(%s, last_error),
                result_redacted = COALESCE(%s, result_redacted),
                result_hash = COALESCE(%s, result_hash),
                erp_reference = COALESCE(%s, erp_reference),
                attempt_count = attempt_count + %s,
                next_reconcile_at = CASE
                    WHEN %s IS NULL THEN next_reconcile_at
                    ELSE now() + (%s * interval '1 second')
                END,
                updated_at = now()
            WHERE operation_id = %s
            """,
            (
                status,
                error,
                Jsonb(result) if result is not None else None,
                result_hash_value,
                erp_reference,
                1 if increment_attempt else 0,
                next_reconcile_seconds,
                next_reconcile_seconds,
                operation_id,
            ),
        )

    @staticmethod
    def _insert_event(
        cur,
        *,
        operation: dict[str, Any],
        event_type: str,
        event_key: str,
        detail: dict[str, Any],
        actor_id: str | None = None,
    ) -> None:
        event_id = f"{operation['operation_id']}:{event_key}"
        cur.execute(
            """
            INSERT INTO audit.write_audit_events(
                event_id, operation_id, event_type, user_id, thread_id,
                tool_name, actor_id, detail
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                operation["operation_id"],
                event_type,
                operation["user_id"],
                operation["thread_id"],
                operation["tool_name"],
                actor_id,
                Jsonb(detail),
            ),
        )
