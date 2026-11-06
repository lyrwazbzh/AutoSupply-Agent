"""Durable ERP write reconciliation worker.

The worker only calls the ERP operation-status endpoint.  It never retries the
original business write, because a lost response cannot prove that ERP did not
apply it.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from prometheus_client import Counter, Gauge

from ...mcp_server.server_config import ERP_BASE_URL
from ..log_utils import middleware_logger
from .notify import notify_manual_required
from .repository import WriteAuditRepository

RECONCILE_INTERVAL_SECONDS = max(
    2, int(os.getenv("WRITE_RECONCILE_INTERVAL_SECONDS", "10"))
)
RECONCILE_MAX_ATTEMPTS = max(
    1, int(os.getenv("WRITE_RECONCILE_MAX_ATTEMPTS", "5"))
)

RECONCILE_TOTAL = Counter(
    "erp_write_reconcile_total",
    "ERP write reconciliation outcomes",
    ("outcome",),
)
MANUAL_REQUIRED = Gauge(
    "erp_write_manual_required",
    "Number of ERP writes escalated for manual reconciliation in this process",
)


class WriteReconciler:
    def __init__(
        self,
        repository: WriteAuditRepository | None = None,
    ) -> None:
        self.repository = repository or WriteAuditRepository()

    async def run(self, stop_event: asyncio.Event) -> None:
        async with httpx.AsyncClient(
            base_url=ERP_BASE_URL,
            timeout=httpx.Timeout(10.0),
        ) as client:
            while not stop_event.is_set():
                await self.run_once(client)
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=RECONCILE_INTERVAL_SECONDS
                    )
                except TimeoutError:
                    pass

    async def run_once(self, client: httpx.AsyncClient) -> None:
        try:
            jobs = await asyncio.to_thread(self.repository.lease_reconcile_jobs)
        except Exception as exc:
            middleware_logger.error("Failed to lease write reconciliation jobs: %s", exc)
            RECONCILE_TOTAL.labels("worker_error").inc()
            return
        for job in jobs:
            await self._reconcile_one(client, job)

    async def _reconcile_one(
        self, client: httpx.AsyncClient, job: dict[str, Any]
    ) -> None:
        operation_id = str(job["operation_id"])
        attempt = int(job.get("attempt_count") or 1)
        try:
            response = await client.get(f"/api/operations/{operation_id}")
            payload = response.json()
            code = int(payload.get("code", response.status_code))
            data = payload.get("data") if isinstance(payload, dict) else None
            data = data if isinstance(data, dict) else {}
            status = str(data.get("status") or "").upper()
            applied = data.get("applied")

            if code == 200 and (applied is True or status in {"SUCCEEDED", "CONFIRMED"}):
                result = data.get("result") or payload
                await asyncio.to_thread(
                    self.repository.finish_reconcile,
                    operation_id,
                    outcome="RECONCILED_SUCCEEDED",
                    detail={"attempt": attempt, "erp_status": data, "result": result},
                )
                RECONCILE_TOTAL.labels("succeeded").inc()
                return

            # Only an explicit ERP statement that the operation was not applied
            # permits retry by a future *new user request*.  The worker itself
            # still never replays the write.
            if applied is False and status in {"NOT_FOUND", "NOT_APPLIED"}:
                await asyncio.to_thread(
                    self.repository.finish_reconcile,
                    operation_id,
                    outcome="NOT_APPLIED",
                    detail={"attempt": attempt, "erp_status": data},
                )
                RECONCILE_TOTAL.labels("not_applied").inc()
                return

            await self._defer_or_escalate(
                job,
                attempt,
                f"ERP returned inconclusive operation state: {payload}",
            )
        except Exception as exc:
            await self._defer_or_escalate(job, attempt, str(exc))

    async def _defer_or_escalate(
        self, job: dict[str, Any], attempt: int, error: str
    ) -> None:
        operation_id = str(job["operation_id"])
        if attempt >= RECONCILE_MAX_ATTEMPTS:
            await asyncio.to_thread(
                self.repository.finish_reconcile,
                operation_id,
                outcome="MANUAL_REQUIRED",
                detail={"attempt": attempt},
                error=error[:4000],
            )
            MANUAL_REQUIRED.inc()
            RECONCILE_TOTAL.labels("manual_required").inc()
            middleware_logger.critical(
                "ERP write reconciliation needs manual action operation=%s attempts=%s error=%s",
                operation_id,
                attempt,
                error,
            )
            try:
                operation = (
                    dict(job["operation"])
                    if isinstance(job.get("operation"), dict)
                    else {}
                )
                operation.setdefault("operation_id", operation_id)
                notify_manual_required(operation, error=error[:4000])
            except Exception as notify_exc:
                middleware_logger.warning(
                    "Failed to notify MANUAL_REQUIRED operation=%s: %s",
                    operation_id,
                    notify_exc,
                )
            return

        retry_seconds = min(1800, 30 * (2 ** (attempt - 1)))
        await asyncio.to_thread(
            self.repository.finish_reconcile,
            operation_id,
            outcome="UNKNOWN",
            detail={"attempt": attempt, "retry_seconds": retry_seconds},
            error=error[:4000],
            retry_seconds=retry_seconds,
        )
        RECONCILE_TOTAL.labels("deferred").inc()
