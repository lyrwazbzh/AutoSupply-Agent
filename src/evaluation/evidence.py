"""Evaluation-environment isolation and ERP evidence collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .models import EvaluationCase


@dataclass
class EvidenceBundle:
    state: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
    operations: dict[str, Any] = field(default_factory=dict)


class EvaluationEnvironment(Protocol):
    async def reset(
        self, case: EvaluationCase, *, run_id: str, trial_index: int
    ) -> None: ...

    async def snapshot(
        self,
        case: EvaluationCase,
        phase: str,
        *,
        run_id: str,
        trial_index: int,
        thread_id: str,
        operation_ids: list[str] | None = None,
    ) -> EvidenceBundle: ...

    async def inject_fault(
        self,
        profile: str,
        *,
        case: EvaluationCase,
        run_id: str,
        trial_index: int,
    ) -> None: ...

    async def clear_faults(
        self,
        *,
        case: EvaluationCase,
        run_id: str,
        trial_index: int,
    ) -> None: ...


class NoopEvaluationEnvironment:
    """Read-only default; refuses cases that require isolated ERP reset."""

    async def reset(
        self, case: EvaluationCase, *, run_id: str, trial_index: int
    ) -> None:
        if case.environment.requires_reset:
            raise RuntimeError("写入评测要求配置独立ERP重置端点")

    async def snapshot(
        self,
        case: EvaluationCase,
        phase: str,
        *,
        run_id: str,
        trial_index: int,
        thread_id: str,
        operation_ids: list[str] | None = None,
    ) -> EvidenceBundle:
        if case.environment.probes:
            raise RuntimeError("用例声明了ERP证据探针，但未配置评测环境")
        return EvidenceBundle()

    async def inject_fault(
        self,
        profile: str,
        *,
        case: EvaluationCase,
        run_id: str,
        trial_index: int,
    ) -> None:
        raise RuntimeError("稳定性故障用例要求配置故障注入端点")

    async def clear_faults(
        self,
        *,
        case: EvaluationCase,
        run_id: str,
        trial_index: int,
    ) -> None:
        return None


class HttpEvaluationEnvironment:
    """HTTP adapter for a dedicated evaluation-profile ERP stack.

    Reset and fault endpoints are deliberately configuration-only. Production
    applications do not need to expose either endpoint.
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        reset_path: str | None = None,
        fault_path: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._reset_path = reset_path
        self._fault_path = fault_path
        self._timeout = timeout_seconds

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=httpx.Timeout(self._timeout),
        ) as client:
            response = await client.request(
                method, path, params=params or {}, json=body or None
            )
            response.raise_for_status()
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text

    @staticmethod
    def _context(
        case: EvaluationCase,
        run_id: str,
        trial_index: int,
        thread_id: str = "",
        operation_id: str = "",
    ) -> dict[str, Any]:
        return {
            "case_id": case.case_id,
            "run_id": run_id,
            "trial_index": trial_index,
            "thread_id": thread_id,
            "operation_id": operation_id,
            "user_id": case.request.user_id,
        }

    async def reset(
        self, case: EvaluationCase, *, run_id: str, trial_index: int
    ) -> None:
        if not case.environment.requires_reset:
            return
        if not self._reset_path:
            raise RuntimeError("写入评测要求配置EVALUATION_RESET_PATH")
        payload = {
            **case.environment.reset_payload,
            **self._context(case, run_id, trial_index),
        }
        await self._request("POST", self._reset_path, body=payload)

    async def snapshot(
        self,
        case: EvaluationCase,
        phase: str,
        *,
        run_id: str,
        trial_index: int,
        thread_id: str,
        operation_ids: list[str] | None = None,
    ) -> EvidenceBundle:
        bundle = EvidenceBundle()
        for probe in case.environment.probes:
            if probe.phase not in {phase, "both"}:
                continue
            target = {
                "state": bundle.state,
                "audit": bundle.audit,
                "operation": bundle.operations,
            }[probe.target]
            probe_operation_ids = (
                operation_ids
                if probe.target == "operation" and "{operation_id}" in probe.path
                else [""]
            ) or []
            collected: dict[str, Any] = {}
            for operation_id in probe_operation_ids:
                context = self._context(
                    case, run_id, trial_index, thread_id, operation_id
                )
                path = probe.path.format_map(context)
                params = {
                    key: (
                        value.format_map(context)
                        if isinstance(value, str)
                        else value
                    )
                    for key, value in probe.params.items()
                }
                body = {
                    key: (
                        value.format_map(context)
                        if isinstance(value, str)
                        else value
                    )
                    for key, value in probe.body.items()
                }
                payload = await self._request(
                    probe.method, path, params=params, body=body
                )
                if operation_id:
                    collected[operation_id] = payload
                else:
                    target[probe.key] = payload
            if collected:
                target[probe.key] = collected
        return bundle

    async def inject_fault(
        self,
        profile: str,
        *,
        case: EvaluationCase,
        run_id: str,
        trial_index: int,
    ) -> None:
        if not self._fault_path:
            raise RuntimeError("故障评测要求配置EVALUATION_FAULT_PATH")
        await self._request(
            "POST",
            self._fault_path,
            body={
                "action": "enable",
                "profile": profile,
                **self._context(case, run_id, trial_index),
            },
        )

    async def clear_faults(
        self,
        *,
        case: EvaluationCase,
        run_id: str,
        trial_index: int,
    ) -> None:
        if not self._fault_path:
            return
        await self._request(
            "POST",
            self._fault_path,
            body={
                "action": "clear",
                **self._context(case, run_id, trial_index),
            },
        )
