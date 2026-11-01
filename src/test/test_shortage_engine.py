"""shortage_engine 金标：对齐 docs/shortage-口径.md 与 shortage_seed。"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "deploy" / "mock-erp"))

from shortage_seed import (  # noqa: E402
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

from agent.shortage.engine import run_shortage_calc  # noqa: E402
from agent.shortage.schemas import (  # noqa: E402
    BomLine,
    CalcConfig,
    InventoryLine,
    OpenPoLine,
    PlanLine,
    SupplierConstraint,
)

AS_OF = datetime(2026, 10, 25)


def _fixture():
    plans_raw = build_plans(AS_OF)
    pos_raw = build_open_pos(AS_OF)
    bom = [
        BomLine(
            part_id=r["partId"],
            qty_per_vehicle=r["qtyPerVehicle"],
            part_code=r["partCode"],
            part_name=r["partName"],
            unit="个",
            purchase_price=10.0,
        )
        for r in BOM_ROWS
    ]
    plans = [
        PlanLine(
            plan_id=p["planId"],
            vehicle_model=p["vehicleModel"],
            plant_id=p["plantId"],
            plan_date=p["planDate"],
            quantity=p["quantity"],
        )
        for p in plans_raw
    ]
    inventory = [
        InventoryLine(part_id=pid, on_hand=qty, allocated=0, inventory_id=pid)
        for pid, qty in INVENTORY_OVERRIDE.items()
    ]
    open_pos = [
        OpenPoLine(
            part_id=r["partId"],
            quantity=r["quantity"],
            expected_date=r["expectedDate"],
            order_number=r["orderNumber"],
            order_status=r["status"],
        )
        for r in pos_raw
    ]
    # 合作中 + A 级；曲轴交期 14 天相对 need_by=D+1 不可达
    suppliers = [
        SupplierConstraint(
            part_id=pid,
            supplier_id=100 + pid,
            supplier_name=f"SUP-{pid}",
            status=1,
            credit_rating="A",
            lead_time_days=PROCUREMENT_PROFILE[pid]["leadTimeDays"],
            moq=PROCUREMENT_PROFILE[pid]["moq"],
            order_multiple=PROCUREMENT_PROFILE[pid]["orderMultiple"],
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
    return config, bom, plans, inventory, open_pos, suppliers


def test_golden_net_gaps():
    config, bom, plans, inventory, open_pos, suppliers = _fixture()
    result = run_shortage_calc(
        config=config,
        bom=bom,
        plans=plans,
        inventory=inventory,
        open_pos=open_pos,
        suppliers=suppliers,
        calc_run_id="test-golden",
    )
    expected = golden_gaps_v2()
    by_id = {ln.part_id: ln for ln in result.lines}
    for pid, gap in expected.items():
        assert by_id[pid].net_gap == gap, f"part {pid}"
        assert by_id[pid].demand_qty == 100 * next(
            r["qtyPerVehicle"] for r in BOM_ROWS if r["partId"] == pid
        )


def test_suggested_qty_moq_and_safety():
    config, bom, plans, inventory, open_pos, suppliers = _fixture()
    result = run_shortage_calc(
        config=config,
        bom=bom,
        plans=plans,
        inventory=inventory,
        open_pos=open_pos,
        suppliers=suppliers,
    )
    # 火花塞 gap=250 → ceil(275)=275 → moq50 → 300
    spark = next(ln for ln in result.lines if ln.part_id == 1)
    assert spark.suggested_qty == 300
    # 蓄电池 D+4 才到货，D+3 峰值 gap=80 → base=88 → 包装倍数10 → 90
    batt = next(ln for ln in result.lines if ln.part_id == 12)
    assert batt.suggested_qty == 90
    assert batt.first_shortage_date == "2026-10-26"
    assert batt.peak_shortage_date == "2026-10-28"
    assert batt.late_in_transit == 30
    # 齐套件建议为 0
    pad = next(ln for ln in result.lines if ln.part_id == 7)
    assert pad.net_gap == 0 and pad.suggested_qty == 0


def test_kit_rate():
    config, bom, plans, inventory, open_pos, suppliers = _fixture()
    result = run_shortage_calc(
        config=config,
        bom=bom,
        plans=plans,
        inventory=inventory,
        open_pos=open_pos,
        suppliers=suppliers,
    )
    # 5 种有需求，其中 2 种齐套（7、18）→ 0.4
    assert result.kit_rate == 0.4
    assert result.gap_part_count == 3
    assert result.demand_part_count == 5
    assert result.caliber_version == "shortage-口径/v2"
    assert result.input_snapshot_id.startswith("snap-")
    assert result.input_hash.startswith("sha256:")
    assert result.result_hash.startswith("sha256:")


def test_explicit_v1_replays_old_gold_without_rewriting_history():
    config, bom, plans, inventory, open_pos, suppliers = _fixture()
    result = run_shortage_calc(
        config=replace(config, caliber_version="shortage-口径/v1"),
        bom=bom,
        plans=plans,
        inventory=inventory,
        open_pos=open_pos,
        suppliers=suppliers,
    )
    assert {line.part_id: line.net_gap for line in result.lines} == golden_gaps()
    assert next(line for line in result.lines if line.part_id == 12).suggested_qty == 60


def test_crankshaft_lead_time_constraint():
    config, bom, plans, inventory, open_pos, suppliers = _fixture()
    result = run_shortage_calc(
        config=config,
        bom=bom,
        plans=plans,
        inventory=inventory,
        open_pos=open_pos,
        suppliers=suppliers,
    )
    crank = next(ln for ln in result.lines if ln.part_id == 4)
    assert crank.net_gap == 90
    assert crank.constraints_ok is False
    assert crank.need_by_date == "2026-10-26"


def test_ceil_to_moq_helper_via_engine():
    # 缺口 1、moq 10、safety 0 → 建议 10
    config = CalcConfig(
        vehicle_model="X",
        plant_id="P",
        as_of="2026-10-25",
        horizon_days=7,
        safety_factor=0.0,
    )
    result = run_shortage_calc(
        config=config,
        bom=[BomLine(part_id=1, qty_per_vehicle=1, purchase_price=1)],
        plans=[
            PlanLine("p1", "X", "P", "2026-10-26", 1),
        ],
        inventory=[InventoryLine(1, 0)],
        open_pos=[],
        suppliers=[
            SupplierConstraint(1, 1, "S", 1, "A", lead_time_days=1, moq=10),
        ],
    )
    assert result.lines[0].net_gap == 1
    assert result.lines[0].suggested_qty == 10


@pytest.mark.parametrize(
    "raw,moq,expected",
    [
        (0, 10, 0),
        (1, 1, 1),
        (11, 10, 20),
        (10, 10, 10),
    ],
)
def test_ceil_to_moq(raw, moq, expected):
    from agent.shortage.engine import _ceil_to_moq

    assert _ceil_to_moq(float(raw), moq) == expected
