"""M2 建议固化、写前校验和幂等建单。"""

from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.shortage.suggestion import (
    assert_payload_matches_calc,
    freeze_shortage_suggestion,
    validate_order_create_payload,
)


def _sample_calc(**overrides):
    base = {
        "calc_run_id": "run-abc",
        "caliber_version": "shortage-口径/v1",
        "vehicle_model": "A-125",
        "plant_id": "PLANT-HZ",
        "kit_rate": 0.4,
        "lines": [
            {
                "part_id": 1,
                "part_code": "P-EN-0001",
                "net_gap": 250,
                "suggested_qty": 300,
                "purchase_price": 25.5,
                "unit": "件",
                "constraints_ok": True,
                "selected_supplier_id": 5,
                "price_ref": "price:1",
            },
            {
                "part_id": 7,
                "part_code": "P-BR-0001",
                "net_gap": 0,
                "suggested_qty": 0,
                "purchase_price": 28.0,
                "unit": "件",
                "constraints_ok": True,
            },
        ],
    }
    base.update(overrides)
    return base


class FreezeSuggestionTests(unittest.TestCase):
    def test_freeze_only_gap_lines(self):
        frozen = freeze_shortage_suggestion(_sample_calc())
        self.assertEqual(frozen["calc_run_id"], "run-abc")
        self.assertTrue(frozen["idempotency_key"].startswith("shortage:"))
        details = frozen["order_payload"]["orderDetail"]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["partId"], 1)
        self.assertEqual(details[0]["quantity"], 300)
        self.assertEqual(details[0]["unitPrice"], 25.5)
        self.assertEqual(frozen["order_payload"]["calc_run_id"], "run-abc")
        self.assertTrue(frozen["payload_hash"].startswith("sha256:"))
        self.assertEqual(details[0]["supplierId"], 5)

    def test_validate_and_match_calc(self):
        frozen = freeze_shortage_suggestion(_sample_calc())
        payload = frozen["order_payload"]
        self.assertEqual(validate_order_create_payload(payload), [])
        self.assertEqual(assert_payload_matches_calc(payload, _sample_calc()), [])

    def test_reject_tampered_qty(self):
        frozen = freeze_shortage_suggestion(_sample_calc())
        payload = frozen["order_payload"]
        payload["orderDetail"][0]["quantity"] = 999
        errs = assert_payload_matches_calc(payload, _sample_calc())
        self.assertTrue(any("数量" in e for e in errs))

    def test_reject_missing_fields(self):
        errs = validate_order_create_payload({"orderDetail": [{"partId": 1}]})
        self.assertTrue(any("quantity" in e for e in errs))

    def test_reject_payload_hash_tamper_and_expiry(self):
        frozen = freeze_shortage_suggestion(_sample_calc(), valid_for_minutes=1)
        payload = frozen["order_payload"]
        payload["plantId"] = "OTHER"
        errs = validate_order_create_payload(payload)
        self.assertTrue(any("payloadHash" in err for err in errs))
        payload = freeze_shortage_suggestion(_sample_calc(), valid_for_minutes=1)["order_payload"]
        future = datetime.now(timezone.utc) + timedelta(minutes=2)
        self.assertTrue(any("过期" in err for err in validate_order_create_payload(payload, now=future)))


class ERPWriteValidationUnitTests(unittest.TestCase):
    def test_guard_rejects_bad_payload(self):
        try:
            from src.agent.middlewares.erp_write import ERPWriteMiddleware
        except ModuleNotFoundError:
            self.skipTest("langchain 未安装")
        mw = ERPWriteMiddleware(repository=object(), user_id="test-user")
        errors = mw._validate(
            "order_create",
            {"order_data": json.dumps({"orderDetail": [{"partId": 1, "quantity": 0, "unitPrice": 1}]})},
            {},
        )
        self.assertTrue(errors)


class MockErpIdempotencyTests(unittest.TestCase):
    def test_idempotent_create(self):
        import importlib
        import sys
        from pathlib import Path

        from fastapi.testclient import TestClient

        mock_dir = Path(__file__).resolve().parents[2] / "deploy" / "mock-erp"
        sys.path.insert(0, str(mock_dir))
        import erp_mock_server as erp

        importlib.reload(erp)
        client = TestClient(erp.app)
        body = {
            "orderNumber": "PO-IDEMP-1",
            "idempotencyKey": "shortage:run-abc",
            "calc_run_id": "run-abc",
            "suggestion_id": "sug-run-abc",
            "orderDetail": [{"partId": 1, "quantity": 10, "unitPrice": 25.5}],
        }
        r1 = client.post("/api/orders/create", json=body)
        r2 = client.post("/api/orders/create", json=body)
        self.assertEqual(r1.json()["code"], 200)
        self.assertEqual(r2.json()["code"], 200)
        self.assertEqual(r1.json()["data"]["id"], r2.json()["data"]["id"])
        self.assertTrue(r2.json()["data"].get("idempotentReplay"))

    def test_same_key_different_payload_conflicts(self):
        import importlib
        import sys
        from pathlib import Path

        from fastapi.testclient import TestClient

        mock_dir = Path(__file__).resolve().parents[2] / "deploy" / "mock-erp"
        sys.path.insert(0, str(mock_dir))
        import erp_mock_server as erp

        importlib.reload(erp)
        client = TestClient(erp.app)
        body = {
            "idempotencyKey": "shortage:conflict",
            "orderDetail": [{"partId": 1, "quantity": 10, "unitPrice": 25.5}],
        }
        self.assertEqual(client.post("/api/orders/create", json=body).json()["code"], 200)
        changed = {**body, "orderDetail": [{"partId": 1, "quantity": 11, "unitPrice": 25.5}]}
        response = client.post("/api/orders/create", json=changed).json()
        self.assertEqual(response["code"], 409)
        self.assertEqual(response["data"]["operationStatus"], "REJECTED")

    def test_concurrent_same_key_creates_one_order(self):
        import importlib
        import sys
        from pathlib import Path

        from fastapi.testclient import TestClient

        mock_dir = Path(__file__).resolve().parents[2] / "deploy" / "mock-erp"
        sys.path.insert(0, str(mock_dir))
        import erp_mock_server as erp

        importlib.reload(erp)
        client = TestClient(erp.app)
        body = {
            "idempotencyKey": "shortage:concurrent",
            "orderDetail": [{"partId": 1, "quantity": 10, "unitPrice": 25.5}],
        }
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda _: client.post("/api/orders/create", json=body).json(), range(16)))
        ids = {row["data"]["id"] for row in rows}
        self.assertEqual(len(ids), 1)
        lookup = client.get("/api/orders/by-idempotency", params={"idempotencyKey": "shortage:concurrent"}).json()
        self.assertEqual(lookup["data"]["operationStatus"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
