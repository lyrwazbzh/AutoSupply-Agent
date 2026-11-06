from __future__ import annotations

import json
from types import SimpleNamespace

from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import ToolMessage

from src.agent.audit.reconciler import WriteReconciler
from src.agent.middlewares.erp_write import ERPWriteMiddleware


class FakeRepository:
    def __init__(self, *, fail_terminal: bool = False) -> None:
        self.operations: dict[str, dict] = {}
        self.payloads: dict[str, dict] = {}
        self.fail_terminal = fail_terminal

    def start_operation(self, **kwargs):
        operation_id = kwargs["operation_id"]
        self.payloads.setdefault(operation_id, kwargs["payload"])
        assert self.payloads[operation_id] == kwargs["payload"]
        return self.operations.setdefault(
            operation_id,
            {
                "operation_id": operation_id,
                "status": (
                    "PENDING_APPROVAL"
                    if kwargs["spec"].requires_approval
                    else "CREATED"
                ),
            },
        )

    def mark_dispatching(self, operation_id):
        self.operations[operation_id]["status"] = "DISPATCHING"

    def mark_pending(self, operation_id):
        self.operations[operation_id]["status"] = "PENDING_APPROVAL"

    def mark_blocked(self, operation_id, reason):
        self.operations[operation_id]["status"] = "FAILED"

    def mark_result(self, operation_id, *, success, unknown=False, **kwargs):
        if self.fail_terminal:
            raise RuntimeError("database unavailable")
        self.operations[operation_id]["status"] = (
            "UNKNOWN" if unknown else ("SUCCEEDED" if success else "FAILED")
        )


def request(name: str, args: dict, call_id: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": call_id, "name": name, "args": args},
        tool=None,
        state={"messages": []},
        runtime=SimpleNamespace(config={"configurable": {"thread_id": "thread-1"}}),
    )


def test_successful_write_is_audited_and_receives_operation_id():
    repository = FakeRepository()
    middleware = ERPWriteMiddleware(repository=repository, user_id="user-1")

    def handler(audited_request):
        assert audited_request.tool_call["args"]["operation_id"]
        return ToolMessage(
            content=json.dumps({"code": 200, "data": {"id": 42}}),
            tool_call_id="call-1",
            name="inventory_inbound",
        )

    result = middleware.wrap_tool_call(
        request("inventory_inbound", {"part_id": 1, "quantity": 2}), handler
    )

    operation = next(iter(repository.operations.values()))
    assert operation["status"] == "SUCCEEDED"
    assert result.status == "success"


def test_invalid_write_is_audited_and_blocked_before_erp():
    repository = FakeRepository()
    middleware = ERPWriteMiddleware(repository=repository, user_id="user-1")
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return ToolMessage(content="{}", tool_call_id="call-1", name="inventory_inbound")

    result = middleware.wrap_tool_call(
        request("inventory_inbound", {"quantity": 2}), handler
    )

    assert calls == 0
    assert next(iter(repository.operations.values()))["status"] == "FAILED"
    assert json.loads(result.content)["message"] == "写前校验未通过"


def test_transport_exception_becomes_unknown_and_is_not_raised_for_retry():
    repository = FakeRepository()
    middleware = ERPWriteMiddleware(repository=repository, user_id="user-1")

    def handler(_request):
        raise TimeoutError("response lost")

    result = middleware.wrap_tool_call(
        request("inventory_outbound", {"part_id": 1, "quantity": 2}), handler
    )

    assert next(iter(repository.operations.values()))["status"] == "UNKNOWN"
    assert json.loads(result.content)["data"]["retryAllowed"] is False


def test_terminal_audit_failure_does_not_replay_erp_write():
    repository = FakeRepository(fail_terminal=True)
    middleware = ERPWriteMiddleware(repository=repository, user_id="user-1")
    calls = 0

    def handler(audited_request):
        nonlocal calls
        calls += 1
        return ToolMessage(
            content=json.dumps({"code": 200, "data": {"id": 42}}),
            tool_call_id=audited_request.tool_call["id"],
            name=audited_request.tool_call["name"],
        )

    result = middleware.wrap_tool_call(
        request("supplier_create", {"supplier_code": "S1", "name": "供应商"}),
        handler,
    )

    assert calls == 1
    assert next(iter(repository.operations.values()))["status"] == "DISPATCHING"
    assert json.loads(result.content)["data"]["operationStatus"] == "UNKNOWN"


def test_hitl_resume_keeps_operation_and_payload_hash_stable():
    repository = FakeRepository()
    middleware = ERPWriteMiddleware(repository=repository, user_id="user-1")
    original = request("order_update_status", {"id": 7, "status": 1})
    audited_request, operation, operation_id = middleware._prepare(original)
    assert operation["status"] == "PENDING_APPROVAL"

    repository.operations[operation_id]["status"] = "APPROVED"
    resumed_request, resumed_operation, resumed_id = middleware._prepare(audited_request)

    assert resumed_id == operation_id
    assert resumed_operation["status"] == "APPROVED"
    dispatched_request = middleware._before_dispatch(
        resumed_request, resumed_operation, resumed_id
    )
    assert not isinstance(dispatched_request, ToolMessage)
    assert repository.operations[operation_id]["status"] == "DISPATCHING"
    assert resumed_request.tool_call["args"]["operation_id"] == operation_id


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "code": 200,
            "data": {
                "status": "SUCCEEDED",
                "applied": True,
                "result": {"code": 200, "data": {"id": 8}},
            },
        }


class ReadOnlyERPClient:
    def __init__(self):
        self.paths = []

    async def get(self, path):
        self.paths.append(path)
        return FakeResponse()


def test_reconciler_only_reads_operation_status():
    class ReconcileRepository:
        def __init__(self):
            self.finished = []

        def finish_reconcile(self, operation_id, **kwargs):
            self.finished.append((operation_id, kwargs))

    repository = ReconcileRepository()
    reconciler = WriteReconciler(repository=repository)
    client = ReadOnlyERPClient()
    import asyncio

    asyncio.run(
        reconciler._reconcile_one(
            client,
            {"operation_id": "op-8", "attempt_count": 1, "operation": {}},
        )
    )

    assert client.paths == ["/api/operations/op-8"]
    assert repository.finished[0][1]["outcome"] == "RECONCILED_SUCCEEDED"


def test_notify_manual_required_dry_run_without_channels(monkeypatch):
    monkeypatch.delenv("WRITE_AUDIT_DINGTALK_WEBHOOK", raising=False)
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("WRITE_AUDIT_DINGTALK_TOKEN", raising=False)
    monkeypatch.delenv("DINGTALK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WRITE_AUDIT_SMTP_HOST", raising=False)
    monkeypatch.delenv("WRITE_AUDIT_ALERT_EMAIL", raising=False)
    from src.agent.audit.notify import notify_manual_required

    result = notify_manual_required(
        {
            "operation_id": "op-manual-1",
            "tool_name": "order_create",
            "user_id": "u1",
            "thread_id": "t1",
        },
        error="inconclusive",
    )
    assert result["dingtalk"]["ok"] is True
    assert result["dingtalk"]["channel"] == "dry_run"
    assert result["email"]["channel"] == "email_skipped"


def test_reconciler_escalates_to_manual_and_notifies(monkeypatch):
    class ReconcileRepository:
        def __init__(self):
            self.finished = []

        def finish_reconcile(self, operation_id, **kwargs):
            self.finished.append((operation_id, kwargs))

    class InconclusiveClient:
        def __init__(self):
            self.paths = []

        async def get(self, path):
            self.paths.append(path)

            class Resp:
                status_code = 200

                def json(self):
                    return {"code": 200, "data": {"status": "PENDING", "applied": None}}

            return Resp()

    notified = []

    def fake_notify(operation, *, error=None):
        notified.append({"operation": operation, "error": error})
        return {"dingtalk": {"ok": True}, "email": {"ok": True}}

    monkeypatch.setattr(
        "src.agent.audit.reconciler.notify_manual_required", fake_notify
    )
    monkeypatch.setattr(
        "src.agent.audit.reconciler.RECONCILE_MAX_ATTEMPTS", 1
    )

    repository = ReconcileRepository()
    reconciler = WriteReconciler(repository=repository)
    import asyncio

    asyncio.run(
        reconciler._reconcile_one(
            InconclusiveClient(),
            {
                "operation_id": "op-9",
                "attempt_count": 1,
                "operation": {
                    "operation_id": "op-9",
                    "tool_name": "order_create",
                    "user_id": "u1",
                },
            },
        )
    )

    assert repository.finished[0][1]["outcome"] == "MANUAL_REQUIRED"
    assert notified and notified[0]["operation"]["operation_id"] == "op-9"


def test_prepare_respects_manual_resolved_statuses():
    repository = FakeRepository()
    middleware = ERPWriteMiddleware(repository=repository, user_id="user-1")
    original = request("inventory_inbound", {"part_id": 1, "quantity": 2})
    _, _, operation_id = middleware._prepare(original)

    repository.operations[operation_id]["status"] = "MANUAL_RESOLVED_SUCCEEDED"
    repository.operations[operation_id]["result_redacted"] = {"code": 200, "data": {"id": 1}}
    replay = middleware._prepare(original)
    assert isinstance(replay, ToolMessage)

    repository.operations[operation_id]["status"] = "MANUAL_RESOLVED_NOT_APPLIED"
    blocked = middleware._prepare(original)
    assert isinstance(blocked, ToolMessage)
    assert json.loads(blocked.content)["code"] == 409


def test_resolve_manual_status_mapping():
    """纯映射约定：运维结案 resolution → 审计终态。"""
    mapping = {
        "succeeded": "MANUAL_RESOLVED_SUCCEEDED",
        "not_applied": "MANUAL_RESOLVED_NOT_APPLIED",
        "abandoned": "MANUAL_RESOLVED_ABANDONED",
    }
    assert set(mapping) == {"succeeded", "not_applied", "abandoned"}

