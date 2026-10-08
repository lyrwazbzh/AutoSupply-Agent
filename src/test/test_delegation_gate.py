"""Task 委派工程化单测（键值抽取 / 证据 / 并发 / Gate 生命周期）。"""
from __future__ import annotations

import unittest

from src.agent.schema import ProcurementContext
from src.agent.subagents.dispatch_events import (
    bind_dispatch_events,
    drain_dispatch_events,
    overlapping_dispatch_pairs,
    reset_dispatch_events,
)
from src.agent.subagents.task_dispatch import (
    SubAgentRegistry,
    TaskDispatchGate,
    TaskDispatchService,
    extract_field_value,
    is_valid_field_value,
    verify_output_contract,
)


def _sample_configs() -> list[dict]:
    return [
        {
            "name": "supply-planning-analyst",
            "context_protocol": {
                "input_context": [
                    {"field": "user_id", "required": True},
                    {"field": "task_objective", "required": True},
                    {"field": "plant", "required": False},
                ],
            },
            "output_format": {
                "sections": ["summary", "data_table", "conclusions"],
            },
        },
        {"name": "strategic-sourcing", "context_protocol": {"input_context": []}},
    ]


def _valid_desc() -> str:
    return (
        "task_objective: 分析工厂A下周缺料与停线风险\n"
        "请结合齐套数据给出可执行的处置建议清单"
    )


class FieldExtractionTests(unittest.TestCase):
    def test_extract_real_value(self):
        text = "task_objective: 分析工厂A下周缺料\nplant: 工厂A"
        self.assertEqual(
            extract_field_value(text, "task_objective"), "分析工厂A下周缺料"
        )
        self.assertEqual(extract_field_value(text, "plant"), "工厂A")

    def test_reject_placeholder(self):
        self.assertFalse(is_valid_field_value("xxx"))
        self.assertFalse(is_valid_field_value("未知"))
        self.assertIsNone(extract_field_value("task_objective: n/a", "task_objective"))


class TaskDispatchServiceTests(unittest.TestCase):
    def setUp(self):
        self.registry = SubAgentRegistry.from_configs(_sample_configs())
        self.ctx = ProcurementContext(user_id="u1", username="alice")
        self.service = TaskDispatchService(
            self.registry, self.ctx, min_description_chars=24, max_parallel=2
        )
        self.token = bind_dispatch_events()

    def tearDown(self):
        reset_dispatch_events(self.token)

    def test_rejects_unknown_type(self):
        ok, reason, *_ = self.service.validate("finance-agent", "x" * 40)
        self.assertFalse(ok)
        self.assertIn("未知", reason)

    def test_rejects_missing_required(self):
        ok, reason, filled, missing, invalid = self.service.validate(
            "supply-planning-analyst",
            "请分析工厂A下周缺料与停线风险，并给出可执行的处置建议清单",
        )
        self.assertFalse(ok)
        self.assertIn("task_objective", missing)
        self.assertIn("user_id", filled)
        self.assertEqual(invalid, [])

    def test_rejects_garbage_value(self):
        ok, reason, filled, missing, invalid = self.service.validate(
            "supply-planning-analyst",
            "task_objective: xxx\n请继续分析工厂缺料风险并给出建议",
        )
        self.assertFalse(ok)
        self.assertIn("task_objective", invalid)
        self.assertIn("无效", reason)

    def test_enrich_includes_extracted_values(self):
        text = _valid_desc()
        ok, _, filled, *_ = self.service.validate("supply-planning-analyst", text)
        self.assertTrue(ok)
        self.assertEqual(filled["task_objective"], "分析工厂A下周缺料与停线风险")
        enriched = self.service.enrich_description(
            "supply-planning-analyst", text, filled
        )
        self.assertIn("user_id: u1", enriched)
        self.assertIn("task_objective: 分析工厂A下周缺料与停线风险", enriched)

    def test_max_parallel_blocks(self):
        svc = TaskDispatchService(
            self.registry, self.ctx, min_description_chars=24, max_parallel=1
        )
        o1 = svc.prepare("supply-planning-analyst", _valid_desc(), "c1")
        self.assertTrue(o1.ok)
        o2 = svc.prepare("supply-planning-analyst", _valid_desc(), "c2")
        self.assertFalse(o2.ok)
        self.assertIn("并发", o2.reason)
        svc.end("c1", status="completed")
        o3 = svc.prepare("supply-planning-analyst", _valid_desc(), "c3")
        self.assertTrue(o3.ok)
        svc.end("c3", status="completed")

    def test_prepare_emits_start_end_events(self):
        outcome = self.service.prepare(
            "supply-planning-analyst", _valid_desc(), "call-1"
        )
        self.assertTrue(outcome.ok, msg=outcome.reason)
        start_events = drain_dispatch_events()
        self.assertEqual(start_events[0]["phase"], "start")
        self.assertIn("started_at", start_events[0])
        obs = self.service.end("call-1", status="completed")
        self.assertIn("finished_at", obs)
        end_events = drain_dispatch_events()
        self.assertEqual(end_events[0]["phase"], "end")

    def test_overlap_pairs(self):
        events = [
            {
                "type": "agent_dispatch",
                "phase": "end",
                "call_id": "a",
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:00:10+00:00",
            },
            {
                "type": "agent_dispatch",
                "phase": "end",
                "call_id": "b",
                "started_at": "2026-01-01T00:00:05+00:00",
                "finished_at": "2026-01-01T00:00:15+00:00",
            },
        ]
        self.assertEqual(overlapping_dispatch_pairs(events), [("a", "b")])


class OutputVerificationTests(unittest.TestCase):
    def test_sections_with_evidence(self):
        text = (
            "## summary\n概述充分\n"
            "## data_table\n| 物料 | 缺口 |\n| --- | --- |\n| M1 | 10 |\n"
            "## conclusions\n结论见 `mrp_shortage_page` 查询\n"
        )
        outcome = verify_output_contract(
            text, ["summary", "data_table", "conclusions"]
        )
        self.assertTrue(outcome.ok, msg=outcome.failure_labels)

    def test_evidence_gap_on_data_table(self):
        text = (
            "## summary\n概述\n"
            "## data_table\n只有文字没有表也没有路径\n"
            "## conclusions\n见 `/workspace/out/chart.png`\n"
        )
        outcome = verify_output_contract(
            text, ["summary", "data_table", "conclusions"]
        )
        self.assertFalse(outcome.ok)
        self.assertIn("data_table", outcome.evidence_gaps)


class TaskDispatchGateTests(unittest.TestCase):
    """无 langchain 依赖的中间件生命周期单测。"""

    def setUp(self):
        self.registry = SubAgentRegistry.from_configs(_sample_configs())
        self.ctx = ProcurementContext(user_id="u1", username="alice")
        self.service = TaskDispatchService(
            self.registry, self.ctx, min_description_chars=24
        )
        self.gate = TaskDispatchGate(self.service)
        self.token = bind_dispatch_events()

    def tearDown(self):
        reset_dispatch_events(self.token)

    def test_reject_unknown(self):
        d = self.gate.before_call("nope", "x" * 40, "c1")
        self.assertEqual(d.action, "reject")
        self.assertIn("未知", d.reason)

    def test_allow_enrich_and_verify_pass(self):
        d = self.gate.before_call(
            "supply-planning-analyst", _valid_desc(), "c9"
        )
        self.assertEqual(d.action, "allow")
        self.assertIn("task_objective: 分析工厂A下周缺料与停线风险", d.enriched_description)
        body = (
            "## summary\nok\n"
            "## data_table\n| a | b |\n| - | - |\n| 1 | 2 |\n"
            "## conclusions\n调用了 `kit_rate_get`\n"
        )
        after = self.gate.after_result("c9", body)
        self.assertEqual(after.action, "allow")
        self.assertEqual(after.end_status, "completed")
        events = drain_dispatch_events()
        self.assertEqual([e["phase"] for e in events], ["start", "end"])

    def test_verification_failed_replace(self):
        self.gate.before_call("supply-planning-analyst", _valid_desc(), "c9")
        drain_dispatch_events()
        after = self.gate.after_result("c9", "## summary\n只有概述")
        self.assertEqual(after.action, "replace")
        self.assertIn("委派结果不合格", after.replace_content)
        self.assertEqual(after.end_status, "verification_failed")
        events = drain_dispatch_events()
        self.assertEqual(events[-1]["status"], "verification_failed")

    def test_timeout_replace(self):
        self.gate.before_call("supply-planning-analyst", _valid_desc(), "c9")
        drain_dispatch_events()
        after = self.gate.on_timeout("c9")
        self.assertEqual(after.action, "replace")
        self.assertIn("超时", after.replace_content)
        events = drain_dispatch_events()
        self.assertEqual(events[-1]["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
