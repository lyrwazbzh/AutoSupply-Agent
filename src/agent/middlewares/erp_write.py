"""Unified validation, idempotency and durable auditing for ERP writes."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from prometheus_client import Counter

from ..audit.payloads import classify_tool_result, payload_hash
from ..audit.registry import WRITE_TOOL_SPECS
from ..audit.repository import WriteAuditRepository
from ..log_utils import middleware_logger
from ..audit.result import ResultAuditor
from ..shortage.actions import (
    record_procurement_result,
    validate_action_retry,
    validate_frozen_suggestion,
)
from ..shortage.records import load_calc_result
from ..shortage.suggestion import (
    assert_payload_matches_calc,
    parse_order_data_arg,
    validate_order_create_payload,
)

AUDIT_FAILURE_TOTAL = Counter(
    "erp_write_audit_failure_total",
    "Write audit persistence failures",
    ("stage",),
)


class ERPWriteMiddleware(AgentMiddleware):
    """Validate and durably track each registered ERP write operation.

    A missing ``requested`` record blocks the write.  A missing terminal record
    never causes the original operation to be replayed: the durable operation
    remains ``DISPATCHING`` and the reconciliation worker owns recovery.
    """

    VALIDATED_WRITE_TOOLS = {
        "order_create",
        "order_update",
        "inventory_inbound",
        "inventory_outbound",
    }

    def __init__(
        self,
        *,
        repository: WriteAuditRepository,
        user_id: str,
        agent_name: str = "main",
        store=None,
    ) -> None:
        self.tools = []
        self.repository = repository
        self.user_id = user_id
        self.agent_name = agent_name
        self.store = store

    @property
    def name(self) -> str:
        return "ERPWriteMiddleware"

    @staticmethod
    def _state(request: ToolCallRequest) -> dict[str, Any]:
        state = getattr(request, "state", None)
        return state if isinstance(state, dict) else {}

    @staticmethod
    def _thread_id(request: ToolCallRequest) -> str:
        runtime = getattr(request, "runtime", None)
        config = getattr(runtime, "config", None)
        if isinstance(config, dict):
            configurable = config.get("configurable") or {}
            if configurable.get("thread_id"):
                return str(configurable["thread_id"])
        state = ERPWriteMiddleware._state(request)
        return str(state.get("thread_id") or "unknown-thread")

    @staticmethod
    def _turn_key(request: ToolCallRequest) -> str:
        messages = ERPWriteMiddleware._state(request).get("messages", [])
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if getattr(message, "type", "") == "human":
                message_id = getattr(message, "id", None)
                if message_id:
                    return str(message_id)
                content = str(getattr(message, "content", ""))
                # The same instruction may legitimately be repeated in a later
                # turn.  Position keeps those writes distinct while remaining
                # stable across HITL resume of this checkpoint.
                return f"{index}:{payload_hash(content)}"
        return "no-human-turn"

    def _identity(
        self, request: ToolCallRequest, tool_name: str, args: dict[str, Any]
    ) -> tuple[str, str, str]:
        thread_id = self._thread_id(request)
        injected_operation_id = args.get("operation_id")
        if injected_operation_id:
            operation_id = str(injected_operation_id)
            return thread_id, operation_id, operation_id
        explicit = self._extract_idempotency_key(args)
        stable_key = explicit or str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                ":".join(
                    (
                        self.user_id,
                        thread_id,
                        self._turn_key(request),
                        tool_name,
                        payload_hash(args),
                    )
                ),
            )
        )
        operation_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"erp-write:{tool_name}:{stable_key}")
        )
        return thread_id, operation_id, stable_key

    @staticmethod
    def _extract_idempotency_key(args: dict[str, Any]) -> str | None:
        for key in ("idempotency_key", "idempotencyKey", "operation_id"):
            if args.get(key):
                return str(args[key])
        order_data = args.get("order_data")
        if isinstance(order_data, str):
            try:
                order_data = json.loads(order_data)
            except (TypeError, ValueError):
                order_data = None
        if isinstance(order_data, dict):
            for key in ("idempotencyKey", "idempotency_key", "operation_id"):
                if order_data.get(key):
                    return str(order_data[key])
        return None

    @staticmethod
    def _unknown_message(request: ToolCallRequest, operation_id: str, message: str) -> ToolMessage:
        return ToolMessage(
            content=json.dumps(
                {
                    "code": 202,
                    "message": message,
                    "data": {
                        "operation_id": operation_id,
                        "operationStatus": "UNKNOWN",
                        "retryAllowed": False,
                    },
                },
                ensure_ascii=False,
            ),
            tool_call_id=request.tool_call.get("id", ""),
            name=request.tool_call.get("name", ""),
            status="error",
            additional_kwargs={
                "write_operation_id": operation_id,
                "write_result_unknown": True,
                "automatic_retry_forbidden": True,
            },
        )

    @staticmethod
    def _replay_message(request: ToolCallRequest, operation: dict[str, Any]) -> ToolMessage:
        result = operation.get("result_redacted") or {
            "code": 200,
            "message": "该幂等写操作已经完成，本次未重复执行",
            "data": {"operation_id": operation["operation_id"]},
        }
        return ToolMessage(
            content=json.dumps(result, ensure_ascii=False, default=str),
            tool_call_id=request.tool_call.get("id", ""),
            name=request.tool_call.get("name", ""),
            status="success",
            additional_kwargs={"write_operation_id": operation["operation_id"], "replayed": True},
        )

    @staticmethod
    def _rejected_message(request: ToolCallRequest, operation_id: str) -> ToolMessage:
        return ToolMessage(
            content=json.dumps(
                {
                    "code": 403,
                    "message": "写操作已被审批拒绝，未调用 ERP",
                    "data": {"operation_id": operation_id},
                },
                ensure_ascii=False,
            ),
            tool_call_id=request.tool_call.get("id", ""),
            name=request.tool_call.get("name", ""),
            status="error",
            additional_kwargs={"write_operation_id": operation_id},
        )

    @staticmethod
    def _inject_operation_id(
        request: ToolCallRequest, operation_id: str
    ) -> ToolCallRequest:
        call = dict(request.tool_call)
        args = dict(call.get("args") or {})
        args.setdefault("operation_id", operation_id)
        call["args"] = args
        return request.override(tool_call=call)

    def _validate(self, tool_name: str, args: dict, state: dict) -> list[str]:
        """Run deterministic business checks for writes that have validators."""
        if tool_name not in self.VALIDATED_WRITE_TOOLS:
            return []
        if state.get("rag_react_mode"):
            return ["有界 ReAct 补搜进行中，禁止写 ERP / 出入库"]

        errors: list[str] = []
        if tool_name in ("inventory_inbound", "inventory_outbound"):
            if not (args.get("part_id") or args.get("part_code") or args.get("data")):
                errors.append(f"{tool_name} 缺少物料或数量参数")
            return errors

        raw = args.get("order_data", args)
        try:
            data = parse_order_data_arg(raw)
        except (ValueError, json.JSONDecodeError, TypeError) as exc:
            return [f"order_data 解析失败: {exc}"]

        errors.extend(validate_order_create_payload(data))
        calc_run_id = data.get("calc_run_id")
        if data.get("suggestion_id") and not calc_run_id:
            errors.append("带有 suggestion_id 的建单必须携带 calc_run_id")

        if calc_run_id:
            snapshots = dict(state.get("calc_snapshots") or {})
            snapshots.update(
                ResultAuditor(store=self.store, user_id=self.user_id).collect_snapshots(state)
            )
            calc = snapshots.get(str(calc_run_id)) or load_calc_result(
                self.store, self.user_id, str(calc_run_id)
            )
            errors.extend(assert_payload_matches_calc(data, calc))
            errors.extend(validate_frozen_suggestion(self.store, self.user_id, data))
            errors.extend(validate_action_retry(self.store, self.user_id, data))

        if tool_name == "order_update" and args.get("id") is None and data.get("id") is None:
            errors.append("order_update 须提供订单 id")
        return errors

    @staticmethod
    def _guard_rejected_message(
        request: ToolCallRequest, operation_id: str, errors: list[str]
    ) -> ToolMessage:
        middleware_logger.warning("ERP write validation rejected: %s", errors)
        return ToolMessage(
            content=json.dumps(
                {
                    "code": 400,
                    "message": "写前校验未通过",
                    "errors": errors,
                    "data": {"operation_id": operation_id},
                },
                ensure_ascii=False,
            ),
            tool_call_id=request.tool_call.get("id", ""),
            status="error",
            name=request.tool_call.get("name", ""),
            additional_kwargs={"write_operation_id": operation_id},
        )

    def _before_dispatch(
        self,
        request: ToolCallRequest,
        operation: dict[str, Any],
        operation_id: str,
    ) -> ToolCallRequest | ToolMessage:
        tool_name = str(request.tool_call.get("name") or "").lower()
        args = dict(request.tool_call.get("args") or {})
        errors = self._validate(tool_name, args, self._state(request))
        if errors:
            try:
                self.repository.mark_blocked(operation_id, "; ".join(errors))
            except Exception as exc:
                middleware_logger.error(
                    "Failed to persist blocked ERP write operation=%s: %s",
                    operation_id,
                    exc,
                )
                AUDIT_FAILURE_TOTAL.labels("guard_blocked").inc()
            return self._guard_rejected_message(request, operation_id, errors)

        spec = WRITE_TOOL_SPECS[tool_name]
        if not spec.requires_approval or operation.get("status") == "APPROVED":
            self.repository.mark_dispatching(operation_id)
        return request

    def _record_order_result(self, request: ToolCallRequest, result: Any) -> None:
        if str(request.tool_call.get("name") or "").lower() != "order_create":
            return
        try:
            args = dict(request.tool_call.get("args") or {})
            data = parse_order_data_arg(args.get("order_data", args))
            record_procurement_result(self.store, self.user_id, data, result)
        except Exception as exc:
            middleware_logger.error("Failed to persist procurement action: %s", exc)

    def _prepare(
        self, request: ToolCallRequest
    ) -> tuple[ToolCallRequest, dict[str, Any], str] | ToolMessage:
        tool_name = str(request.tool_call.get("name") or "").lower()
        spec = WRITE_TOOL_SPECS.get(tool_name)
        if spec is None:
            return request, {}, ""
        args = dict(request.tool_call.get("args") or {})
        thread_id, operation_id, idempotency_key = self._identity(request, tool_name, args)
        audit_payload = dict(args)
        # operation_id is gateway metadata injected after the original audit
        # record.  Excluding it keeps the payload hash stable across HITL resume.
        audit_payload.pop("operation_id", None)
        operation = self.repository.start_operation(
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            tool_call_id=str(request.tool_call.get("id") or operation_id),
            thread_id=thread_id,
            user_id=self.user_id,
            agent_name=self.agent_name,
            tool_name=tool_name,
            spec=spec,
            payload=audit_payload,
        )
        status = operation["status"]
        if status in {"SUCCEEDED", "RECONCILED_SUCCEEDED"}:
            return self._replay_message(request, operation)
        if status == "REJECTED":
            return self._rejected_message(request, operation_id)
        if status in {"DISPATCHING", "UNKNOWN", "RECONCILING", "MANUAL_REQUIRED"}:
            return self._unknown_message(
                request,
                operation_id,
                "该写操作已派发或结果待对账，禁止自动重试",
            )
        if status in {"FAILED", "NOT_APPLIED"}:
            return ToolMessage(
                content=json.dumps(
                    {
                        "code": 409,
                        "message": "本轮相同写操作已经失败；如需重试，请由用户发起新的明确请求",
                        "data": {"operation_id": operation_id, "retryAllowed": False},
                    },
                    ensure_ascii=False,
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=tool_name,
                status="error",
            )
        return self._inject_operation_id(request, operation_id), operation, operation_id

    def _finish(
        self, request: ToolCallRequest, operation_id: str, result: Any
    ) -> Any:
        success, parsed, error, erp_reference = classify_tool_result(result)
        if error == "ERP_RESULT_UNKNOWN":
            self.repository.mark_result(
                operation_id,
                success=False,
                result=parsed,
                error=error,
                erp_reference=erp_reference,
                unknown=True,
            )
            self._attach_operation_id(result, operation_id)
            return result
        self.repository.mark_result(
            operation_id,
            success=success,
            result=parsed,
            error=error,
            erp_reference=erp_reference,
        )
        self._attach_operation_id(result, operation_id)
        return result

    @staticmethod
    def _attach_operation_id(result: Any, operation_id: str) -> None:
        if isinstance(result, ToolMessage):
            result.additional_kwargs["write_operation_id"] = operation_id

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        name = str(request.tool_call.get("name") or "").lower()
        if name not in WRITE_TOOL_SPECS:
            return await handler(request)
        try:
            prepared = await asyncio.to_thread(self._prepare, request)
        except Exception as exc:
            middleware_logger.error("Write audit preflight failed; ERP call blocked: %s", exc)
            AUDIT_FAILURE_TOTAL.labels("preflight").inc()
            return ToolMessage(
                content=json.dumps(
                    {"code": 503, "message": "写审计不可用，已阻止 ERP 写入", "error": str(exc)},
                    ensure_ascii=False,
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=name,
                status="error",
            )
        if isinstance(prepared, ToolMessage):
            return prepared
        audited_request, operation, operation_id = prepared
        try:
            before_dispatch = await asyncio.to_thread(
                self._before_dispatch, audited_request, operation, operation_id
            )
        except Exception as exc:
            middleware_logger.error("ERP write validation failed closed: %s", exc)
            AUDIT_FAILURE_TOTAL.labels("validation").inc()
            return ToolMessage(
                content=json.dumps(
                    {"code": 503, "message": "写治理不可用，已阻止 ERP 写入", "error": str(exc)},
                    ensure_ascii=False,
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=name,
                status="error",
            )
        if isinstance(before_dispatch, ToolMessage):
            return before_dispatch
        audited_request = before_dispatch
        try:
            result = await handler(audited_request)
        except BaseException as exc:
            # LangGraph interrupts suspend execution; they are not write failures.
            if exc.__class__.__name__ in {"GraphInterrupt", "NodeInterrupt"}:
                try:
                    await asyncio.to_thread(self.repository.mark_pending, operation_id)
                except Exception as audit_exc:
                    middleware_logger.error(
                        "Failed to reaffirm pending approval operation=%s: %s",
                        operation_id,
                        audit_exc,
                    )
                    AUDIT_FAILURE_TOTAL.labels("approval_pending").inc()
                raise
            try:
                await asyncio.to_thread(
                    self.repository.mark_result,
                    operation_id,
                    success=False,
                    result={"exception": type(exc).__name__},
                    error=str(exc),
                    unknown=True,
                )
            except Exception as audit_exc:
                middleware_logger.critical(
                    "ERP write transport exception and audit update both failed operation=%s: %s",
                    operation_id,
                    audit_exc,
                )
                AUDIT_FAILURE_TOTAL.labels("unknown_result").inc()
            return self._unknown_message(
                request,
                operation_id,
                "ERP 写请求发生传输异常，执行结果未知；禁止自动重试，系统将执行对账",
            )
        await asyncio.to_thread(self._record_order_result, audited_request, result)
        try:
            return await asyncio.to_thread(self._finish, audited_request, operation_id, result)
        except Exception as exc:
            middleware_logger.critical(
                "ERP returned but terminal audit failed operation=%s; reconciliation required: %s",
                operation_id,
                exc,
            )
            AUDIT_FAILURE_TOTAL.labels("terminal").inc()
            return self._unknown_message(
                request,
                operation_id,
                "ERP 已接收请求，但终态审计保存失败；禁止自动重试，系统将执行对账",
            )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        name = str(request.tool_call.get("name") or "").lower()
        if name not in WRITE_TOOL_SPECS:
            return handler(request)
        try:
            prepared = self._prepare(request)
        except Exception as exc:
            middleware_logger.error("Write audit preflight failed; ERP call blocked: %s", exc)
            AUDIT_FAILURE_TOTAL.labels("preflight").inc()
            return ToolMessage(
                content=json.dumps(
                    {"code": 503, "message": "写审计不可用，已阻止 ERP 写入", "error": str(exc)},
                    ensure_ascii=False,
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=name,
                status="error",
            )
        if isinstance(prepared, ToolMessage):
            return prepared
        audited_request, operation, operation_id = prepared
        try:
            before_dispatch = self._before_dispatch(
                audited_request, operation, operation_id
            )
        except Exception as exc:
            middleware_logger.error("ERP write validation failed closed: %s", exc)
            AUDIT_FAILURE_TOTAL.labels("validation").inc()
            return ToolMessage(
                content=json.dumps(
                    {"code": 503, "message": "写治理不可用，已阻止 ERP 写入", "error": str(exc)},
                    ensure_ascii=False,
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=name,
                status="error",
            )
        if isinstance(before_dispatch, ToolMessage):
            return before_dispatch
        audited_request = before_dispatch
        try:
            result = handler(audited_request)
        except BaseException as exc:
            if exc.__class__.__name__ in {"GraphInterrupt", "NodeInterrupt"}:
                try:
                    self.repository.mark_pending(operation_id)
                except Exception as audit_exc:
                    middleware_logger.error(
                        "Failed to reaffirm pending approval operation=%s: %s",
                        operation_id,
                        audit_exc,
                    )
                    AUDIT_FAILURE_TOTAL.labels("approval_pending").inc()
                raise
            try:
                self.repository.mark_result(
                    operation_id,
                    success=False,
                    result={"exception": type(exc).__name__},
                    error=str(exc),
                    unknown=True,
                )
            except Exception as audit_exc:
                middleware_logger.critical(
                    "ERP write transport exception and audit update both failed operation=%s: %s",
                    operation_id,
                    audit_exc,
                )
                AUDIT_FAILURE_TOTAL.labels("unknown_result").inc()
            return self._unknown_message(
                request,
                operation_id,
                "ERP 写请求发生传输异常，执行结果未知；禁止自动重试，系统将执行对账",
            )
        self._record_order_result(audited_request, result)
        try:
            return self._finish(audited_request, operation_id, result)
        except Exception as exc:
            middleware_logger.critical(
                "ERP returned but terminal audit failed operation=%s; reconciliation required: %s",
                operation_id,
                exc,
            )
            AUDIT_FAILURE_TOTAL.labels("terminal").inc()
            return self._unknown_message(
                request,
                operation_id,
                "ERP 已接收请求，但终态审计保存失败；禁止自动重试，系统将执行对账",
            )
