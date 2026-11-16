"""Keep the test-only Mock on the same core envelope/operation contract as Java ERP."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_mock_module():
    path = Path(__file__).parents[2] / "deploy" / "mock-erp" / "erp_mock_server.py"
    spec = importlib.util.spec_from_file_location("erp_mock_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOCK = _load_mock_module()


def test_success_and_error_envelopes_have_java_compatible_fields() -> None:
    success = MOCK.ok({"id": 1})
    error_response = MOCK.fail("conflict", 409)
    error = json.loads(error_response.body)

    assert set(success) == {"code", "message", "data"}
    assert set(error) == {"code", "message", "data"}
    assert success["code"] == 200
    assert error["code"] == 409
    assert error_response.status_code == 200


def test_operation_replay_uses_java_compatible_fields_and_original_result() -> None:
    operation_id = "contract-operation"
    original = MOCK.ok({"id": 7}, "created")

    completed = MOCK.complete_operation(operation_id, original)
    replayed = MOCK.replay_operation(operation_id)
    operation = MOCK.store.operations[operation_id]

    assert completed == original
    assert replayed == original
    assert {"operationId", "status", "applied", "result", "updatedAt"} <= set(operation)
    assert operation["applied"] is True


def test_order_hash_uses_the_canonical_pending_status_and_ignores_gateway_metadata() -> None:
    payload = {"orderDetail": [{"partId": 1, "quantity": 2, "unitPrice": 3}], "status": 0}
    canonical = {
        "orderDetail": [{"partId": 1, "quantity": 2, "unitPrice": 3}],
        "status": 1,
        "operationId": "different-request-metadata",
    }

    assert MOCK._business_payload_hash(payload) == MOCK._business_payload_hash(canonical)
