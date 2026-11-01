"""v2 时间口径、数据质量、快照回放和字段级审计回归。"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agent.audit import ResultAuditor
from src.agent.shortage.actions import (
    load_procurement_action,
    persist_frozen_suggestion,
    record_procurement_result,
    validate_action_retry,
    validate_frozen_suggestion,
)
from src.agent.shortage.engine import run_shortage_calc
from src.agent.shortage.records import (
    build_calc_record,
    load_calc_result,
    persist_calc_record,
    replay_calc_record,
)
from src.agent.shortage.report import build_verified_facts, render_verified_summary
from src.agent.shortage.schemas import (
    BomLine,
    CalcConfig,
    InventoryLine,
    OpenPoLine,
    PlanLine,
    SupplierConstraint,
)
from src.agent.shortage.suggestion import freeze_shortage_suggestion
from src.agent.shortage.validation import InputValidationError


def _single_calc(
    *,
    demand: int = 200,
    on_hand: int = 80,
    receipt_qty: int = 150,
    receipt_date: str = "2026-11-05",
    moq: int = 1,
    multiple: int = 1,
    safety: float = 0,
):
    return run_shortage_calc(
        config=CalcConfig("X", "P", "2026-10-27", 10, safety),
        bom=[BomLine(1, 1, "PART-1", "测试件", "件", 2.5, "BOM-X-1", "PRICE-1")],
        plans=[PlanLine("plan-1", "X", "P", "2026-11-02", demand)],
        inventory=[InventoryLine(1, on_hand, 0, 1, "件")],
        open_pos=[OpenPoLine(1, receipt_qty, receipt_date, "PO-1", 2, "件")],
        suppliers=[SupplierConstraint(1, 10, "供应商A", 1, "A", 1, moq, multiple)],
        calc_run_id="v2-single",
        source_versions={"bom": "BOM-X-1", "inventory": "INV-9"},
    )


def test_late_receipt_does_not_hide_earlier_shortage():
    result = _single_calc()
    line = result.lines[0]
    assert line.net_gap == 120
    assert line.first_shortage_date == "2026-11-02"
    assert line.peak_shortage_date == "2026-11-02"
    assert line.late_in_transit == 150
    assert line.timeline[-1]["net_gap"] == 0


def test_moq_and_order_multiple_are_independent():
    result = _single_calc(
        demand=65, on_hand=0, receipt_qty=0, receipt_date="2026-11-01",
        moq=50, multiple=20, safety=0.1,
    )
    line = result.lines[0]
    assert line.base_qty == 72
    assert line.moq == 50
    assert line.order_multiple == 20
    assert line.suggested_qty == 80


def test_duplicate_bom_lines_aggregate_and_input_order_is_deterministic():
    config = CalcConfig("X", "P", "2026-10-27", 3, 0)
    bom = [
        BomLine(2, 1, "P2", "件2", "件", 1),
        BomLine(1, 0.5, "P1", "件1", "件", 1),
        BomLine(1, 0.5, "P1", "件1", "件", 1),
    ]
    plans = [PlanLine("b", "X", "P", "2026-10-29", 4), PlanLine("a", "X", "P", "2026-10-28", 6)]
    inventory = [InventoryLine(2, 0, inventory_id=2), InventoryLine(1, 0, inventory_id=1)]
    suppliers = [
        SupplierConstraint(2, 2, "S2", 1, "A", 0),
        SupplierConstraint(1, 1, "S1", 1, "A", 0),
    ]
    first = run_shortage_calc(
        config=config, bom=bom, plans=plans, inventory=inventory,
        open_pos=[], suppliers=suppliers, calc_run_id="same",
    )
    random.Random(7).shuffle(bom)
    random.Random(8).shuffle(plans)
    random.Random(9).shuffle(inventory)
    random.Random(10).shuffle(suppliers)
    second = run_shortage_calc(
        config=config, bom=bom, plans=plans, inventory=inventory,
        open_pos=[], suppliers=suppliers, calc_run_id="same",
    )
    assert next(line for line in first.lines if line.part_id == 1).demand_qty == 10
    assert first.input_hash == second.input_hash
    assert first.result_hash == second.result_hash


@pytest.mark.parametrize(
    "inventory,po",
    [
        ([InventoryLine(1, 2, 3)], []),
        ([InventoryLine(1, 2, 0, unit="箱")], []),
        ([InventoryLine(1, -1, 0)], []),
    ],
)
def test_invalid_business_inputs_are_rejected(inventory, po):
    with pytest.raises(InputValidationError):
        run_shortage_calc(
            config=CalcConfig("X", "P", "2026-10-27"),
            bom=[BomLine(1, 1, unit="件", purchase_price=1)],
            plans=[PlanLine("p", "X", "P", "2026-10-28", 1)],
            inventory=inventory,
            open_pos=po,
            suppliers=[SupplierConstraint(1, 1, "S", 1, "A", 1)],
        )


def test_snapshot_record_replays_exactly():
    result = _single_calc()
    record = build_calc_record(result)
    replay = replay_calc_record(record)
    assert replay["matched"] is True
    assert record.input_hash == result.input_hash
    assert record.result_hash == result.result_hash


def test_auditor_rejects_right_number_assigned_to_wrong_part():
    calc = {
        "calc_run_id": "audit-1",
        "caliber_version": "shortage-口径/v2",
        "kit_rate": 0,
        "lines": [
            {"part_id": 1, "part_code": "SPARK", "part_name": "火花塞", "unit": "件", "net_gap": 250, "suggested_qty": 300},
            {"part_id": 2, "part_code": "BATT", "part_name": "蓄电池", "unit": "件", "net_gap": 50, "suggested_qty": 60},
        ],
    }
    audit = ResultAuditor().audit({
        "calc_snapshots": {"audit-1": calc},
        "messages": [
            ToolMessage(content=json.dumps({"code": 200, "data": calc}, ensure_ascii=False), name="shortage_calc", tool_call_id="1"),
            AIMessage(content="火花塞缺口 50 件，calc_run_id=audit-1"),
        ],
    })
    assert audit.action == "reject"
    assert any(finding.code == "business_fact_mismatch" for finding in audit.findings)


def test_structured_fact_checks_part_metric_unit_value_tuple():
    result = _single_calc()
    calc = result.to_dict()
    facts = build_verified_facts(calc)
    assert ResultAuditor().audit_facts(facts, calc) == []
    bad = [dict(facts[0], value=999, unit="箱")]
    findings = ResultAuditor().audit_facts(bad, calc)
    assert {finding.code for finding in findings} == {"fact_value_mismatch", "fact_unit_mismatch"}
    assert "净缺口 120.0" in render_verified_summary(calc)


@dataclass
class _Item:
    value: dict


class _Store:
    def __init__(self):
        self.data = {}

    def get(self, namespace, key):
        value = self.data.get((namespace, key))
        return _Item(value) if value else None

    def put(self, namespace, key, value):
        self.data[(namespace, key)] = value


def test_calc_record_store_is_immutable_and_cross_session_readable():
    store = _Store()
    record = build_calc_record(_single_calc()).to_dict()
    persist_calc_record(store, "u1", record)
    persist_calc_record(store, "u1", record)
    assert load_calc_result(store, "u1", "v2-single")["result_hash"] == record["result_hash"]
    changed = dict(record, record_hash="sha256:different")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        persist_calc_record(store, "u1", changed)


def test_frozen_approval_and_action_state_are_persistent():
    store = _Store()
    frozen = freeze_shortage_suggestion(_single_calc().to_dict())
    payload = frozen["order_payload"]
    persist_frozen_suggestion(store, "u1", frozen)
    assert validate_frozen_suggestion(store, "u1", payload) == []
    tampered = dict(payload, payloadHash="sha256:tampered")
    assert validate_frozen_suggestion(store, "u1", tampered)
    record_procurement_result(
        store, "u1", payload, {"code": 202, "data": {"operationStatus": "UNKNOWN"}}
    )
    assert load_procurement_action(store, "u1", payload["idempotencyKey"])["status"] == "UNKNOWN"
    assert any("回查" in error for error in validate_action_retry(store, "u1", payload))
