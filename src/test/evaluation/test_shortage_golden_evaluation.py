"""
采购评测黄金集（不启完整 Agent，串联确定性模块 + mock-erp）。

覆盖规划验收：
- 缺槽位澄清
- A-125 缺料金标数值
- 固化建议 → 幂等建单 → 回查
- 写安全（篡改数量被拒、假下单声称被拒）
- RAG 制度问答带 source
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "deploy" / "mock-erp"))

from langchain_core.messages import HumanMessage
from shortage_seed import (
    BOM_ROWS,
    INVENTORY_OVERRIDE,
    PLANT_ID,
    PROCUREMENT_PROFILE,
    VEHICLE_MODEL,
    build_open_pos,
    build_plans,
    golden_gaps,
    golden_gaps_v2,
)

from src.agent.audit import ResultAuditor
from src.agent.knowledge.evidence import assess_evidence
from src.agent.knowledge.retrieve import hybrid_retrieve
from src.agent.knowledge.store import get_default_store
from src.agent.review_policy import ReviewPolicy
from src.agent.shortage.engine import run_shortage_calc
from src.agent.shortage.schemas import (
    BomLine,
    CalcConfig,
    InventoryLine,
    OpenPoLine,
    PlanLine,
    SupplierConstraint,
)
from src.agent.shortage.suggestion import (
    assert_payload_matches_calc,
    freeze_shortage_suggestion,
    validate_order_create_payload,
)
from src.api_view.evaluation_metrics import MetricsBoard

AS_OF = datetime(2026, 10, 25)


def _calc_fixture():
    plans_raw = build_plans(AS_OF)
    pos_raw = build_open_pos(AS_OF)
    # 单价用演示价；金标缺口不依赖单价
    price_map = {1: 25.5, 7: 28.0, 12: 118.0, 4: 385.0, 18: 65.0}
    bom = [
        BomLine(
            part_id=r["partId"],
            qty_per_vehicle=r["qtyPerVehicle"],
            part_code=r["partCode"],
            part_name=r["partName"],
            unit="个",
            purchase_price=price_map.get(r["partId"], 10.0),
        )
        for r in BOM_ROWS
    ]
    plans = [
        PlanLine(p["planId"], p["vehicleModel"], p["plantId"], p["planDate"], p["quantity"])
        for p in plans_raw
    ]
    inventory = [
        InventoryLine(pid, qty, 0, pid) for pid, qty in INVENTORY_OVERRIDE.items()
    ]
    open_pos = [
        OpenPoLine(r["partId"], r["quantity"], r["expectedDate"], r["orderNumber"], r["status"])
        for r in pos_raw
    ]
    suppliers = [
        SupplierConstraint(
            pid, 100 + pid, f"SUP-{pid}", 1, "A",
            PROCUREMENT_PROFILE[pid]["leadTimeDays"],
            PROCUREMENT_PROFILE[pid]["moq"],
            PROCUREMENT_PROFILE[pid]["orderMultiple"],
        )
        for pid in INVENTORY_OVERRIDE
    ]
    config = CalcConfig(
        vehicle_model=VEHICLE_MODEL,
        plant_id=PLANT_ID,
        as_of=AS_OF.strftime("%Y-%m-%d"),
        horizon_days=7,
        safety_factor=0.1,
    )
    return run_shortage_calc(
        config=config,
        bom=bom,
        plans=plans,
        inventory=inventory,
        open_pos=open_pos,
        suppliers=suppliers,
        calc_run_id="evaluation-golden-run",
    )


METRICS = MetricsBoard()


class ShortageGoldenEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = _calc_fixture()
        cls.calc = cls.result.to_dict()

    def test_01_review_scope_for_shortage(self):
        t0 = time.perf_counter()
        from src.agent.harness import load_harness_config

        route = ReviewPolicy(load_harness_config()).start(
            {"messages": [HumanMessage(content="分析未来7天缺料风险并提出补货建议")]}
        )
        ok = route["review_decision"]["task_type"] == "shortage" and bool(route["rubric"])
        METRICS.add(
            "review_scope_shortage",
            ok,
            category="task_success",
            detail=str(route["review_decision"]),
            ms=(time.perf_counter() - t0) * 1000,
        )
        self.assertTrue(ok)

    def test_02_review_scope_with_business_context(self):
        t0 = time.perf_counter()
        from src.agent.harness import load_harness_config

        route = ReviewPolicy(load_harness_config()).start(
            {"messages": [HumanMessage(content=(
                f"分析车型 {VEHICLE_MODEL} 在工厂 {PLANT_ID} 未来7天缺料风险"
            ))]}
        )
        ok = route["review_decision"]["decision"] == "review"
        METRICS.add(
            "review_scope_ready",
            ok,
            category="task_success",
            detail=str(route["review_decision"]),
            ms=(time.perf_counter() - t0) * 1000,
        )
        self.assertTrue(ok)

    def test_03_golden_net_gaps(self):
        t0 = time.perf_counter()
        expected = golden_gaps_v2()
        by_id = {ln.part_id: ln.net_gap for ln in self.result.lines}
        ok = all(by_id.get(pid) == gap for pid, gap in expected.items())
        METRICS.add(
            "numeric_gaps",
            ok,
            category="numeric_accuracy",
            detail=f"kit_rate={self.result.kit_rate} gaps={ {k: by_id[k] for k in expected} }",
            ms=(time.perf_counter() - t0) * 1000,
        )
        self.assertTrue(ok)
        self.assertEqual(self.result.kit_rate, 0.4)

    def test_04_freeze_and_validate(self):
        t0 = time.perf_counter()
        frozen = freeze_shortage_suggestion(self.calc)
        errs = validate_order_create_payload(frozen["order_payload"])
        match = assert_payload_matches_calc(frozen["order_payload"], self.calc)
        ok = not errs and not match and frozen["calc_run_id"] == "evaluation-golden-run"
        METRICS.add(
            "freeze_validate",
            ok,
            category="task_success",
            detail=f"lines={frozen['line_count']}",
            ms=(time.perf_counter() - t0) * 1000,
        )
        self.assertTrue(ok)

    def test_05_idempotent_create_and_verify(self):
        t0 = time.perf_counter()
        import importlib

        import erp_mock_server as erp
        from fastapi.testclient import TestClient

        importlib.reload(erp)
        client = TestClient(erp.app)
        frozen = freeze_shortage_suggestion(self.calc)
        payload = frozen["order_payload"]
        r1 = client.post("/api/orders/create", json=payload)
        r2 = client.post("/api/orders/create", json=payload)
        d1, d2 = r1.json()["data"], r2.json()["data"]
        verify = client.get(f"/api/orders/get/{d1['id']}")
        ok = (
            r1.json()["code"] == 200
            and d1["id"] == d2["id"]
            and d2.get("idempotentReplay") is True
            and verify.json()["code"] == 200
            and verify.json()["data"]["orderNumber"] == d1["orderNumber"]
        )
        METRICS.add(
            "idempotent_write_verify",
            ok,
            category="task_success",
            detail=f"order_id={d1['id']} replay={d2.get('idempotentReplay')}",
            ms=(time.perf_counter() - t0) * 1000,
        )
        self.assertTrue(ok)

    def test_06_write_safety_tamper_rejected(self):
        t0 = time.perf_counter()
        frozen = freeze_shortage_suggestion(self.calc)
        payload = dict(frozen["order_payload"])
        payload["orderDetail"] = [dict(payload["orderDetail"][0])]
        payload["orderDetail"][0]["quantity"] = 99999
        errs = assert_payload_matches_calc(payload, self.calc)
        ok = len(errs) > 0
        METRICS.add(
            "write_safety_tamper",
            ok,
            category="write_safety",
            detail=";".join(errs[:2]),
            ms=(time.perf_counter() - t0) * 1000,
        )
        self.assertTrue(ok)

    def test_07_write_safety_fake_success_claim(self):
        t0 = time.perf_counter()
        from langchain_core.messages import AIMessage

        audit = ResultAuditor().audit(
            {
                "messages": [AIMessage(content="订单已创建成功，单号 PO-FAKE")],
            }
        )
        ok = audit.action == "reject"
        METRICS.add(
            "write_safety_claim",
            ok,
            category="write_safety",
            detail=audit.action,
            ms=(time.perf_counter() - t0) * 1000,
        )
        self.assertTrue(ok)

    def test_08_rag_citation_coverage(self):
        t0 = time.perf_counter()
        store = get_default_store()
        result = hybrid_retrieve("供应商准入信用等级 A B", domain="avl", store=store)
        assessment = assess_evidence(result)
        cited = sum(1 for h in result["hits"] if h.get("source") and h.get("version"))
        coverage = cited / len(result["hits"]) if result["hits"] else 0
        ok = assessment.sufficient and coverage >= 0.9
        METRICS.add(
            "rag_citation",
            ok,
            category="rag",
            detail=f"coverage={coverage:.2f} hits={len(result['hits'])}",
            ms=(time.perf_counter() - t0) * 1000,
        )
        self.assertTrue(ok)

    @classmethod
    def tearDownClass(cls):
        summary = METRICS.summary()
        out = ROOT / "src" / "test" / "evaluation" / "last_evaluation_report.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path = METRICS.dump()
        print("\n===== E2E Golden Summary =====")
        print(json.dumps(summary.get("kpis"), ensure_ascii=False, indent=2))
        print(f"evaluation report -> {report_path}")


if __name__ == "__main__":
    unittest.main()
