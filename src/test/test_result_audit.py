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


class ResultAuditorTests(unittest.TestCase):
    def test_reject_shortage_numbers_without_calc(self):
        state = {
            "messages": [
                HumanMessage(content="分析车型 A-125 工厂 PLANT-HZ 缺料"),
                AIMessage(
                    content="缺口 250，建议量 300，齐套率 0.4。以下为缺料分析结论摘要。"
                    + "x" * 50
                ),
            ],
        }
        audit = ResultAuditor().audit(state)
        self.assertEqual(audit.action, "reject")
        self.assertTrue(any(f.code == "shortage_without_calc" for f in audit.findings))

    def test_pass_with_calc_snapshot_alignment(self):
        calc = {
            "calc_run_id": "run-1",
            "caliber_version": "shortage-口径/v1",
            "kit_rate": 0.4,
            "lines": [
                {"part_id": 1, "net_gap": 250, "suggested_qty": 300, "demand_qty": 400},
            ],
            "total_gap_amount": 100.0,
            "gap_part_count": 3,
            "demand_part_count": 5,
        }
        state = {
            "calc_snapshots": {"run-1": calc},
            "messages": [
                ToolMessage(
                    content=json.dumps({"code": 200, "data": calc}, ensure_ascii=False),
                    name="shortage_calc",
                    tool_call_id="1",
                ),
                AIMessage(
                    content="缺口 250，建议量 300，齐套率 0.4。calc_run_id=run-1"
                ),
            ],
        }
        audit = ResultAuditor().audit(state)
        self.assertNotEqual(audit.action, "reject")
        self.assertIn("run-1", audit.calc_run_ids)

    def test_reject_write_claim_without_tool(self):
        state = {
            "messages": [AIMessage(content="订单已创建成功，单号 PO001")],
        }
        audit = ResultAuditor().audit(state)
        self.assertEqual(audit.action, "reject")

@unittest.skipUnless(_HARNESS, "langchain/deepagents 未安装")
class HarnessReviewWireTests(unittest.TestCase):
    def test_before_agent_injects_review_route_and_rubric(self):
        mw = HarnessPhaseMiddleware()
        state = {
            "messages": [HumanMessage(content="分析未来7天缺料风险并提出补货建议")],
        }
        updates = mw.before_agent(state, runtime=None)
        self.assertNotIn("intent", updates)
        self.assertTrue(updates.get("rubric"))
        self.assertEqual(updates["review_decision"]["source"], "rule")
        self.assertEqual(updates["review_decision"]["task_type"], "shortage")

    def test_shortage_config_present(self):
        cfg = load_harness_config()
        self.assertIn("shortage", cfg.get("task_types", {}))
        self.assertIn("shortage", cfg.get("rubrics", {}))


if __name__ == "__main__":
    unittest.main()
