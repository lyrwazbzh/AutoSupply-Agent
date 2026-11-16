"""Isolated multi-trial runner for the four-dimension evaluation."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Iterable

import httpx

from .claims import ClaimExtractor
from .evidence import (
    EvaluationEnvironment,
    NoopEvaluationEnvironment,
)
from .models import (
    CaseObservation,
    EvaluationCase,
    EvaluationResult,
    EvaluationSuite,
    ReportMetadata,
    ToolCallObservation,
)
from .oracle import EvaluationOracle, ReportAggregator
from .report_store import dump_report


def load_jsonl(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            cases.append(EvaluationCase.model_validate_json(raw))
        except Exception as exc:
            raise ValueError(f"无效评测用例 {path}:{line_number}: {exc}") from exc
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError(f"数据集包含重复case_id: {path}")
    return cases


def parse_sse(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Parse complete SSE lines; deliberately independent from HTTP for tests."""

    events: list[dict[str, Any]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in [*lines, ""]:
        if line == "":
            if data_lines:
                payload_text = "\n".join(data_lines)
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError:
                    payload = {"raw": payload_text}
                events.append({"event": event_name, "data": payload})
            event_name = "message"
            data_lines = []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    return events


async def _collect_sse(response: httpx.Response) -> list[dict[str, Any]]:
    event_name = "message"
    data_lines: list[str] = []
    events: list[dict[str, Any]] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                payload_text = "\n".join(data_lines)
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError:
                    payload = {"raw": payload_text}
                events.append({"event": event_name, "data": payload})
            event_name = "message"
            data_lines = []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if data_lines:
        events.extend(
            parse_sse(
                [f"event: {event_name}", *[f"data: {item}" for item in data_lines]]
            )
        )
    return events


def _decoded(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _classify_tool_result(content: Any) -> tuple[str, str]:
    payload = _decoded(content)
    if isinstance(payload, dict) and isinstance(payload.get("code"), int):
        code = payload["code"]
        if code == 200:
            return "success", "none"
        if code == 400:
            return "error", "agent"
        if 500 <= code < 600:
            return "error", "infra"
        return "error", "business"
    return "success", "none"


def _find_operation_id(value: Any) -> str | None:
    value = _decoded(value)
    if isinstance(value, dict):
        for key in ("operation_id", "operationId"):
            if value.get(key):
                return str(value[key])
        for item in value.values():
            found = _find_operation_id(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_operation_id(item)
            if found:
                return found
    return None


def observation_from_events(
    events: list[dict[str, Any]], case: EvaluationCase
) -> CaseObservation:
    answer: list[str] = []
    calls: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    infra_error: str | None = None
    saw_terminal = False
    clarification_interrupt = False
    for item in events:
        event = item.get("event")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if event == "token" and data.get("source", "main") == "main":
            answer.append(str(data.get("content") or ""))
        elif event == "tool_start":
            calls.append(
                {
                    "id": str(data.get("id") or uuid.uuid4()),
                    "name": str(data.get("name") or "unknown"),
                    "arguments": "",
                    "result": None,
                    "status": "interrupted",
                    "error_source": "none",
                }
            )
        elif event == "tool_args" and calls:
            calls[-1]["arguments"] += str(data.get("args") or "")
        elif event == "tool_result":
            name = str(data.get("name") or "unknown")
            result_call_id = str(data.get("id") or data.get("tool_call_id") or "")
            target = next(
                (
                    call
                    for call in reversed(calls)
                    if result_call_id and call["id"] == result_call_id
                ),
                None,
            )
            if target is None:
                target = next(
                    (
                        call
                        for call in reversed(calls)
                        if call["name"] == name and call["result"] is None
                    ),
                    None,
                )
            if target is None:
                target = {
                    "id": result_call_id or str(uuid.uuid4()),
                    "name": name,
                    "arguments": "",
                    "result": None,
                    "status": "interrupted",
                    "error_source": "none",
                }
                calls.append(target)
            target["result"] = data.get("content")
            target["status"], target["error_source"] = _classify_tool_result(
                data.get("content")
            )
        elif event in {"phase", "review_result"}:
            trace.append({"type": event, **data})
        elif event == "interrupt":
            saw_terminal = True
            trace.append({"type": "interrupt", **data})
            if data.get("interrupt_type") == "order_info_supplement":
                clarification_interrupt = True
                if data.get("message"):
                    answer.append(str(data["message"]))
        elif event == "error":
            saw_terminal = True
            infra_error = str(data.get("message") or "Agent SSE error")
        elif event == "done":
            saw_terminal = True

    if not saw_terminal and infra_error is None:
        infra_error = "Agent SSE未返回done、interrupt或error终态事件"

    tool_calls = [
        ToolCallObservation(
            call_id=call["id"],
            sequence=index,
            name=call["name"],
            arguments=_decoded(call["arguments"]),
            result=_decoded(call["result"]),
            status=call["status"],
            error_source=call["error_source"],
            operation_id=_find_operation_id(call["result"]),
        )
        for index, call in enumerate(calls, 1)
    ]
    final_answer = "".join(answer).strip()
    markers = case.expected.clarification_markers
    asked = clarification_interrupt or (
        ("?" in final_answer or "？" in final_answer) and bool(final_answer)
    )
    correct_clarification = None
    if case.expected.should_clarify:
        correct_clarification = asked and all(
            marker.casefold() in final_answer.casefold() for marker in markers
        )
    return CaseObservation(
        final_answer=final_answer,
        tool_calls=tool_calls,
        asked_clarification=asked,
        correct_clarification=correct_clarification,
        infra_error=infra_error,
        raw_events=events,
        harness_trace=trace,
    )


class AgentSseClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        approval_headers: dict[str, str] | None = None,
        timeout_seconds: float = 300.0,
        fetch_persisted_trace: bool = False,
    ):
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._approval_headers = approval_headers or {}
        self._timeout = timeout_seconds
        self._fetch_persisted_trace = fetch_persisted_trace

    async def _post_stream(
        self, path: str, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self._timeout)
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            async with client.stream(
                "POST", f"{self._base_url}{path}", json=payload
            ) as response:
                response.raise_for_status()
                return await _collect_sse(response)

    async def _post_approval(
        self, operation_id: str, decision: dict[str, Any]
    ) -> None:
        if not self._approval_headers:
            raise RuntimeError("写操作评测需要独立 EVALUATION_APPROVER_BEARER_TOKEN")
        payload = {
            "decision": decision.get("type"),
            "note": decision.get("message", "evaluation checker"),
            "payload_hash": decision.get("payload_hash", ""),
        }
        timeout = httpx.Timeout(self._timeout)
        async with httpx.AsyncClient(
            timeout=timeout, headers=self._approval_headers
        ) as client:
            response = await client.post(
                f"{self._base_url}/api/write-audit/approvals/{operation_id}/decision",
                json=payload,
            )
            response.raise_for_status()

    async def _get_harness_trace(self, thread_id: str) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self._timeout)
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            response = await client.get(
                f"{self._base_url}/api/evaluation/traces/{thread_id}"
            )
            response.raise_for_status()
            payload = response.json()
            return list(payload.get("trace") or [])

    async def run(
        self,
        case: EvaluationCase,
        *,
        run_id: str = "",
        trial_index: int = 1,
        thread_id: str | None = None,
    ) -> CaseObservation:
        request = case.request.model_dump(mode="json")
        request["thread_id"] = (
            thread_id
            or request.get("thread_id")
            or f"eval-{case.case_id.lower()}-{trial_index}-{run_id[:8]}"
        )
        try:
            events = await self._post_stream("/api/chat/stream", request)
            first = observation_from_events(events, case)
            interrupted = any(item.get("event") == "interrupt" for item in events)
            if interrupted and case.resume_decisions:
                interrupt = next(
                    item.get("data", {})
                    for item in events
                    if item.get("event") == "interrupt"
                )
                operation_ids = list(interrupt.get("operation_ids") or [])
                if len(operation_ids) != len(case.resume_decisions):
                    raise RuntimeError("评测审批决定数量与 operation_id 数量不一致")
                for operation_id, decision in zip(
                    operation_ids, case.resume_decisions
                ):
                    await self._post_approval(str(operation_id), decision)
                resumed = await self._post_stream(
                    f"/api/chat/{request['thread_id']}/resume",
                    {"resume": {"check_approval": True}},
                )
                events.extend(resumed)
                first = observation_from_events(events, case)
            first.run_id = run_id
            first.trial_index = trial_index
            if self._fetch_persisted_trace:
                first.harness_trace = await self._get_harness_trace(
                    str(request["thread_id"])
                )
            return first
        except (httpx.HTTPError, OSError, RuntimeError) as exc:
            return CaseObservation(
                run_id=run_id,
                trial_index=trial_index,
                infra_error=f"Agent API不可用: {exc}",
            )


class EvaluationRunner:
    def __init__(
        self,
        client: AgentSseClient,
        extractor: ClaimExtractor,
        environment: EvaluationEnvironment | None = None,
    ):
        self._client = client
        self._extractor = extractor
        self._environment = environment or NoopEvaluationEnvironment()
        self._oracle = EvaluationOracle()

    @staticmethod
    def _trial_case(case: EvaluationCase, trial_index: int) -> EvaluationCase:
        stability = case.expected.stability
        if not stability or not stability.input_variants:
            return case
        variant = stability.input_variants[
            (trial_index - 1) % len(stability.input_variants)
        ]
        trial_case = case.model_copy(deep=True)
        trial_case.request.message = variant
        return trial_case

    async def run_case(
        self,
        case: EvaluationCase,
        *,
        trial_index: int = 1,
        fault_profile: str | None = None,
    ) -> EvaluationResult:
        trial_case = self._trial_case(case, trial_index)
        run_id = str(uuid.uuid4())
        thread_id = f"eval-{case.case_id.lower()}-{trial_index}-{run_id[:8]}"
        fault_injected = False
        observation = CaseObservation(run_id=run_id, trial_index=trial_index)
        try:
            await self._environment.reset(
                trial_case, run_id=run_id, trial_index=trial_index
            )
            if fault_profile:
                await self._environment.inject_fault(
                    fault_profile,
                    case=trial_case,
                    run_id=run_id,
                    trial_index=trial_index,
                )
                fault_injected = True
            before = await self._environment.snapshot(
                trial_case,
                "before",
                run_id=run_id,
                trial_index=trial_index,
                thread_id=thread_id,
                operation_ids=[],
            )
            observation = await self._client.run(
                trial_case,
                run_id=run_id,
                trial_index=trial_index,
                thread_id=thread_id,
            )
            after = await self._environment.snapshot(
                trial_case,
                "after",
                run_id=run_id,
                trial_index=trial_index,
                thread_id=thread_id,
                operation_ids=[
                    call.operation_id
                    for call in observation.tool_calls
                    if call.operation_id
                ],
            )
            observation.state_before = before.state
            observation.state_after = after.state
            observation.audit_records = after.audit
            observation.operation_records = after.operations
        except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
            observation.infra_error = f"评测环境不可用: {exc}"
        finally:
            if fault_profile:
                try:
                    await self._environment.clear_faults(
                        case=trial_case,
                        run_id=run_id,
                        trial_index=trial_index,
                    )
                except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                    observation.infra_error = f"故障注入清理失败: {exc}"

        observation.run_id = run_id
        observation.trial_index = trial_index
        observation.fault_profile = fault_profile
        observation.fault_injected = fault_injected
        observation.fault_recovered = (
            observation.infra_error is None if fault_injected else None
        )
        if observation.infra_error is None and not case.expected.should_clarify:
            try:
                observation.claims = await self._extractor.extract(
                    trial_case, observation.final_answer, observation.tool_calls
                )
            except Exception as exc:
                observation.infra_error = f"业务声明抽取失败: {exc}"
        return self._oracle.evaluate(trial_case, observation)

    async def run_all(
        self,
        cases: list[EvaluationCase],
        metadata: ReportMetadata,
        *,
        output: Path | None = None,
        suites: set[EvaluationSuite] | None = None,
        trials: int | None = None,
        fault_profiles: list[str] | None = None,
    ):
        selected = [
            case
            for case in cases
            if not suites or case.enabled_suites().intersection(suites)
        ]
        results: list[EvaluationResult] = []
        for case in selected:
            stability = case.expected.stability
            configured_trials = stability.trials if stability else 1
            trial_count = max(configured_trials, trials or 1)
            profiles = fault_profiles or (stability.fault_profiles if stability else [])
            for trial_index in range(1, trial_count + 1):
                profile = (
                    profiles[(trial_index - 1) % len(profiles)] if profiles else None
                )
                results.append(
                    await self.run_case(
                        case,
                        trial_index=trial_index,
                        fault_profile=profile,
                    )
                )
        report = ReportAggregator().build(results, metadata)
        dump_report(report, output)
        return report
