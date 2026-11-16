"""钉钉 HITL 适配层单测（不连开放平台）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import unittest
from unittest.mock import patch

from src.api_view.dingtalk_channel import (
    DingTalkStreamConsumer,
    map_dingtalk_user,
    parse_approval_callback,
    publish_approval,
    render_approval_card,
    verify_dingtalk_sign,
)


def _frozen():
    return {
        "suggestion_id": "sug-demo",
        "evidence_id": "",
        "idempotency_key": "order:demo:1",
        "operation_id": "op-demo-1",
        "total_amount": 510.0,
        "order_payload": {
            "orderNumber": "PO20260101001",
            "totalAmount": 510.0,
            "status": 1,
            "idempotencyKey": "order:demo:1",
            "orderDetail": [
                {"partId": 1, "quantity": 20, "unitPrice": 25.5},
            ],
        },
    }


class DingTalkHitlTests(unittest.TestCase):
    def test_map_known_user(self):
        ident = map_dingtalk_user("ding-buyer-001")
        self.assertIsNotNone(ident)
        self.assertEqual(ident.agent_user_id, "buyer")
        self.assertIn("purchaser", ident.roles)

    def test_map_unknown_user(self):
        self.assertIsNone(map_dingtalk_user("nobody"))

    def test_render_card_interactive(self):
        card = render_approval_card(thread_id="t-1", frozen_suggestion=_frozen())
        self.assertEqual(card.thread_id, "t-1")
        self.assertEqual(card.suggestion_id, "sug-demo")
        self.assertTrue(card.order_payload.get("idempotencyKey"))
        self.assertTrue(card.interactive_card.get("contents"))

    def test_callback_to_independent_approval(self):
        out = parse_approval_callback(
            {
                "dingtalk_userid": "ding-admin-001",
                "decision": "approve",
                "operation_id": "op-1",
                "card_id": "card-x",
            }
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["approval_decision"]["decision"], "approve")
        self.assertEqual(out["approval_decision"]["operation_id"], "op-1")

    def test_callback_nested_value(self):
        out = parse_approval_callback(
            {
                "userId": "ding-admin-001",
                "value": {
                    "decision": "reject",
                    "card_id": "c1",
                    "operation_id": "op-9",
                },
            }
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["approval_decision"]["decision"], "reject")
        self.assertEqual(out["approval_decision"]["operation_id"], "op-9")

    def test_callback_reject_unknown_user(self):
        out = parse_approval_callback(
            {"dingtalk_userid": "x", "decision": "approve", "operation_id": "op"}
        )
        self.assertFalse(out["ok"])

    def test_publisher_dry_run(self):
        out = publish_approval(thread_id="t-dry", frozen_suggestion=_frozen())
        self.assertTrue(out["push"]["ok"])
        self.assertEqual(out["push"]["channel"], "dry_run")

    def test_stream_dedup(self):
        c = DingTalkStreamConsumer()
        ev = {
            "eventId": "e-1",
            "type": "card_callback",
            "data": {
                "dingtalk_userid": "ding-admin-001",
                "decision": "approve",
                "operation_id": "op-stream",
            },
        }
        r1 = c.handle_event(ev)
        r2 = c.handle_event(ev)
        self.assertTrue(r1.get("ok"))
        self.assertTrue(r2.get("dedup"))

    def test_sign_rejects_when_no_secret(self):
        with patch.dict(
            "os.environ",
            {"DINGTALK_CALLBACK_SECRET": "", "DINGTALK_SKIP_SIGN": "0"},
            clear=False,
        ):
            self.assertFalse(verify_dingtalk_sign("1", "x"))

    def test_sign_accepts_valid_hmac(self):
        secret = "test-callback-secret"
        timestamp = "1700000000000"
        digest = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}\n{secret}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        sign = base64.b64encode(digest).decode("utf-8")
        self.assertTrue(verify_dingtalk_sign(timestamp, sign, secret=secret))

    def test_sign_skip_requires_explicit_development_flag(self):
        with patch.dict(
            "os.environ",
            {"DINGTALK_CALLBACK_SECRET": "", "DINGTALK_SKIP_SIGN": "1"},
            clear=False,
        ):
            self.assertTrue(verify_dingtalk_sign("", ""))


if __name__ == "__main__":
    unittest.main()
