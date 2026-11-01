"""钉钉 HITL 适配层单测（不连开放平台）。"""

from __future__ import annotations

import unittest

from src.api_view.dingtalk_channel import (
    DingTalkCardPublisher,
    DingTalkStreamConsumer,
    map_dingtalk_user,
    parse_approval_callback,
    publish_shortage_approval,
    render_approval_card,
    verify_dingtalk_sign,
)
from src.agent.shortage.suggestion import freeze_shortage_suggestion


def _calc():
    return {
        "calc_run_id": "run-ding",
        "caliber_version": "shortage-口径/v1",
        "vehicle_model": "A-125",
        "plant_id": "PLANT-HZ",
        "lines": [
            {
                "part_id": 1,
                "part_code": "P-EN-0001",
                "net_gap": 10,
                "suggested_qty": 20,
                "purchase_price": 25.5,
            }
        ],
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
        frozen = freeze_shortage_suggestion(_calc())
        card = render_approval_card(thread_id="t-1", frozen_suggestion=frozen)
        self.assertEqual(card.thread_id, "t-1")
        self.assertEqual(card.calc_run_id, "run-ding")
        self.assertTrue(card.order_payload.get("idempotencyKey"))
        self.assertTrue(card.interactive_card.get("contents"))
        self.assertTrue(any("calc_run_id" in line for line in card.summary_lines))

    def test_callback_to_hitl_approve(self):
        out = parse_approval_callback(
            {
                "dingtalk_userid": "ding-buyer-001",
                "decision": "approve",
                "thread_id": "t-1",
                "card_id": "card-x",
            }
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["hitl_resume"]["decisions"][0]["type"], "approve")

    def test_callback_nested_value(self):
        out = parse_approval_callback(
            {
                "userId": "ding-buyer-001",
                "value": {
                    "decision": "reject",
                    "card_id": "c1",
                    "thread_id": "t-9",
                },
            }
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["hitl_resume"]["decisions"][0]["type"], "reject")
        self.assertEqual(out["thread_id"], "t-9")

    def test_callback_reject_unknown_user(self):
        out = parse_approval_callback(
            {"dingtalk_userid": "x", "decision": "approve", "thread_id": "t"}
        )
        self.assertFalse(out["ok"])

    def test_publisher_dry_run(self):
        frozen = freeze_shortage_suggestion(_calc())
        out = publish_shortage_approval(thread_id="t-dry", frozen_suggestion=frozen)
        self.assertTrue(out["push"]["ok"])
        self.assertEqual(out["push"]["channel"], "dry_run")

    def test_stream_dedup(self):
        c = DingTalkStreamConsumer()
        ev = {
            "eventId": "e-1",
            "type": "card_callback",
            "data": {
                "dingtalk_userid": "ding-buyer-001",
                "decision": "approve",
                "thread_id": "t",
            },
        }
        r1 = c.handle_event(ev)
        r2 = c.handle_event(ev)
        self.assertTrue(r1.get("ok"))
        self.assertTrue(r2.get("dedup"))

    def test_sign_skip_when_no_secret(self):
        self.assertTrue(verify_dingtalk_sign("1", "x"))


if __name__ == "__main__":
    unittest.main()
