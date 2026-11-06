"""ReviewPolicy + ResultAuditor 单测（结果审计门禁）。"""

from __future__ import annotations

import json
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.audit import ResultAuditor

try:
    from src.agent.harness import HarnessPhaseMiddleware, load_harness_config
    _HARNESS = True
except ModuleNotFoundError:
    _HARNESS = False


def _tool(name: str, payload: dict, tool_call_id: str = "1") -> ToolMessage:
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        name=name,
        tool_call_id=tool_call_id,
    )


class ResultAuditorTests(unittest.TestCase):
    def test_reject_write_claim_without_tool(self):
        state = {
            "messages": [AIMessage(content="订单已创建成功，单号 PO20260101001")],
        }
        audit = ResultAuditor().audit(state)
        self.assertEqual(audit.action, "reject")
        self.assertTrue(any(f.code == "write_claim_without_tool" for f in audit.findings))

    def test_reject_inventory_claim_without_tool(self):
        state = {"messages": [AIMessage(content="入库成功，数量已更新")]}
        audit = ResultAuditor().audit(state)
        self.assertEqual(audit.action, "reject")
        self.assertTrue(any(f.code == "write_claim_without_tool" for f in audit.findings))

    def test_reject_claim_after_write_failure(self):
        state = {
            "messages": [
                _tool(
                    "order_create",
                    {"code": 400, "message": "库存不足", "data": None},
                ),
                AIMessage(content="订单已创建成功"),
            ],
        }
        audit = ResultAuditor().audit(state)
        self.assertEqual(audit.action, "reject")
        self.assertTrue(
            any(f.code == "claim_after_write_failure" for f in audit.findings)
        )

    def test_pass_when_order_tool_succeeded(self):
        state = {
            "messages": [
                _tool(
                    "order_create",
                    {
                        "code": 200,
                        "message": "success",
                        "data": {
                            "id": 1,
                            "orderNumber": "PO20260101001",
                            "totalAmount": 510.0,
                        },
                    },
                ),
                AIMessage(
                    content="订单已创建成功，单号 PO20260101001，金额 510.00 元"
                ),
            ],
        }
        audit = ResultAuditor().audit(state)
        self.assertEqual(audit.action, "pass")

    def test_reject_answer_value_not_in_receipt(self):
        state = {
            "messages": [
                _tool(
                    "order_create",
                    {
                        "code": 200,
                        "message": "success",
                        "data": {
                            "id": 1,
                            "orderNumber": "PO20260101001",
                            "totalAmount": 510.0,
                        },
                    },
                ),
                AIMessage(
                    content="订单已创建成功，单号 PO99999999，金额 999.00 元"
                ),
            ],
        }
        audit = ResultAuditor().audit(state)
        self.assertEqual(audit.action, "reject")
        codes = {f.code for f in audit.findings}
        self.assertIn("answer_value_not_in_receipt", codes)

    def test_warn_on_write_tool_error_without_success_claim(self):
        state = {
            "messages": [
                _tool(
                    "inventory_outbound",
                    {"code": 400, "message": "库存不足", "data": None},
                ),
                AIMessage(content="出库失败，当前库存不足，请确认数量后重试。"),
            ],
        }
        audit = ResultAuditor().audit(state)
        self.assertEqual(audit.action, "warn")
        self.assertTrue(any(f.code == "write_tool_error" for f in audit.findings))


@unittest.skipUnless(_HARNESS, "langchain/deepagents 未安装")
class HarnessReviewWireTests(unittest.TestCase):
    def test_before_agent_injects_review_route_and_rubric(self):
        mw = HarnessPhaseMiddleware()
        state = {
            "messages": [HumanMessage(content="分析近 7 天采购订单金额趋势并提出建议")],
        }
        updates = mw.before_agent(state, runtime=None)
        self.assertNotIn("intent", updates)
        self.assertTrue(updates.get("rubric"))
        self.assertEqual(updates["review_decision"]["source"], "rule")
        self.assertEqual(updates["review_decision"]["task_type"], "analysis")

    def test_core_task_types_present(self):
        cfg = load_harness_config()
        for key in ("analysis", "order", "inventory", "supplier"):
            self.assertIn(key, cfg.get("task_types", {}))
            self.assertIn(key, cfg.get("rubrics", {}))


if __name__ == "__main__":
    unittest.main()
