"""确定性缺料计算引擎：v2 按日供需，保留显式 v1 回放能力。"""

from __future__ import annotations

import math
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from .records import build_input_snapshot, finalize_result
from .schemas import (
    CALIBER_VERSION,
    ENGINE_VERSION,
    LEGACY_CALIBER_VERSION,
    BomLine,
    CalcConfig,
    CalcResult,
    GapLine,
    InventoryLine,
    OpenPoLine,
    PlanLine,
    SupplierConstraint,
)
from .validation import InputValidationError, validate_shortage_inputs

MONEY = Decimal("0.01")


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _parse_day(value: str) -> datetime:
    return datetime.strptime(value[:10], "%Y-%m-%d")


def _day_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _window_end(as_of: str, horizon_days: int) -> datetime:
    return _parse_day(as_of) + timedelta(days=max(1, horizon_days) - 1)


def _ceil_decimal(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING)) if value > 0 else 0


def _ceil_to_moq(raw: float, moq: int) -> int:
    """v1 兼容函数：历史口径把 MOQ 同时当成订购倍数。"""

    qty = int(math.ceil(raw)) if raw > 0 else 0
    if qty <= 0:
        return 0
    moq = max(1, int(moq))
    if moq <= 1:
        return qty
    return int(math.ceil(qty / moq) * moq)


def _apply_quantity_policy(base_qty: int, moq: int, order_multiple: int) -> int:
    """v2：MOQ 是下限，order_multiple 是独立的包装/订购倍数。"""

    if base_qty <= 0:
        return 0
    minimum = max(int(base_qty), max(1, int(moq)))
    multiple = max(1, int(order_multiple))
    return int(math.ceil(minimum / multiple) * multiple)


def _in_window(plan_date: str, as_of: str, horizon_days: int) -> bool:
    day = _parse_day(plan_date)
    return _parse_day(as_of) <= day <= _window_end(as_of, horizon_days)


def _decimal_number(value: Decimal) -> float:
    return float(value)


def _money(value: Decimal) -> float:
    return float(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def _aggregate_bom(rows: list[BomLine]) -> list[BomLine]:
    merged: dict[int, BomLine] = {}
    quantities: dict[int, Decimal] = {}
    for row in rows:
        if row.part_id not in merged:
            merged[row.part_id] = row
            quantities[row.part_id] = Decimal(0)
        quantities[row.part_id] += _d(row.qty_per_vehicle)
    return [
        replace(merged[pid], qty_per_vehicle=float(quantities[pid]))
        for pid in sorted(merged)
    ]


def _aggregate_inventory(rows: list[InventoryLine]) -> tuple[dict[int, InventoryLine], dict[int, list[str]]]:
    totals: dict[int, list[int]] = {}
    refs: dict[int, list[str]] = {}
    for row in rows:
        if row.status.lower() not in ("available", "可用"):
            continue
        total = totals.setdefault(row.part_id, [0, 0])
        total[0] += row.on_hand
        total[1] += row.allocated
        if row.inventory_id is not None:
            refs.setdefault(row.part_id, []).append(str(row.inventory_id))
    return (
        {
            pid: InventoryLine(part_id=pid, on_hand=value[0], allocated=value[1])
            for pid, value in totals.items()
        },
        {pid: sorted(values) for pid, values in refs.items()},
    )


def _risk_level(as_of: str, shortage_date: Optional[str], constraints_ok: bool) -> str:
    if not shortage_date:
        return "none"
    if not constraints_ok:
        return "critical"
    days = (_parse_day(shortage_date) - _parse_day(as_of)).days
    if days <= 1:
        return "critical"
    if days <= 3:
        return "high"
    return "medium"


def run_shortage_calc(
    *,
    config: CalcConfig,
    bom: Iterable[BomLine],
    plans: Iterable[PlanLine],
    inventory: Iterable[InventoryLine],
    open_pos: Iterable[OpenPoLine],
    suppliers: Iterable[SupplierConstraint],
    calc_run_id: Optional[str] = None,
    source_versions: Optional[dict[str, Any]] = None,
    source_read_times: Optional[dict[str, str]] = None,
    captured_at: Optional[str] = None,
) -> CalcResult:
    """执行确定性计算。

    默认使用 ``shortage-口径/v2``。历史记录只有在配置显式声明 v1 时才走旧公式，
    从而既不篡改旧金标，又让新请求获得时间维度与分离的数量约束。
    """

    bom_input = list(bom)
    plans_input = list(plans)
    inventory_input = list(inventory)
    po_input = list(open_pos)
    supplier_input = list(suppliers)
    errors, warnings = validate_shortage_inputs(
        config=config,
        bom=bom_input,
        plans=plans_input,
        inventory=inventory_input,
        open_pos=po_input,
        suppliers=supplier_input,
    )
    if errors:
        raise InputValidationError(errors)
    all_warnings = [issue.message for issue in warnings]

    snapshot = build_input_snapshot(
        config=config,
        bom=bom_input,
        plans=plans_input,
        inventory=inventory_input,
        open_pos=po_input,
        suppliers=supplier_input,
        source_versions=source_versions,
        source_read_times=source_read_times,
        captured_at=captured_at,
    )
    bom_rows = _aggregate_bom(bom_input)
    inv_map, inventory_refs = _aggregate_inventory(inventory_input)
    supplier_by_part: dict[int, list[SupplierConstraint]] = {}
    for row in supplier_input:
        supplier_by_part.setdefault(row.part_id, []).append(row)

    start = _parse_day(config.as_of)
    window_end = _window_end(config.as_of, config.horizon_days)
    window_end_s = _day_str(window_end)
    matched_plans = sorted([
        row
        for row in plans_input
        if row.vehicle_model == config.vehicle_model
        and row.plant_id == config.plant_id
        and _in_window(row.plan_date, config.as_of, config.horizon_days)
    ], key=lambda row: (row.plan_date, row.plan_id))

    demand_by_part_day: dict[int, dict[str, Decimal]] = {}
    need_by: dict[int, str] = {}
    plan_refs: dict[int, list[str]] = {}
    for plan in matched_plans:
        day = plan.plan_date[:10]
        for bline in bom_rows:
            daily = demand_by_part_day.setdefault(bline.part_id, {})
            daily[day] = daily.get(day, Decimal(0)) + _d(plan.quantity) * _d(bline.qty_per_vehicle)
            plan_refs.setdefault(bline.part_id, []).append(plan.plan_id)
            if bline.part_id not in need_by or day < need_by[bline.part_id]:
                need_by[bline.part_id] = day

    receipt_by_part_day: dict[int, dict[str, int]] = {}
    transit_refs: dict[int, list[str]] = {}
    active_receipts: dict[int, list[OpenPoLine]] = {}
    for po in po_input:
        if po.order_status not in (1, 2):
            continue
        remaining = po.quantity - po.received_qty
        if remaining <= 0:
            continue
        active_receipts.setdefault(po.part_id, []).append(po)
        day = po.expected_date[:10]
        # 已逾期但仍未收货的单据不能自动当成 as_of 可用供给。
        if day < config.as_of[:10] or _parse_day(day) > window_end:
            continue
        receipt_days = receipt_by_part_day.setdefault(po.part_id, {})
        receipt_days[day] = receipt_days.get(day, 0) + remaining
        if po.order_number:
            transit_refs.setdefault(po.part_id, []).append(po.order_number)
    transit_refs = {pid: sorted(refs) for pid, refs in transit_refs.items()}

    lines: list[GapLine] = []
    legacy = config.caliber_version == LEGACY_CALIBER_VERSION
    if config.caliber_version not in (LEGACY_CALIBER_VERSION, CALIBER_VERSION):
        raise ValueError(f"不支持的缺料口径: {config.caliber_version}")

    for bline in bom_rows:
        pid = bline.part_id
        daily_demand = demand_by_part_day.get(pid, {})
        daily_receipts = receipt_by_part_day.get(pid, {})
        total_demand = sum(daily_demand.values(), Decimal(0))
        inv = inv_map.get(pid) or InventoryLine(part_id=pid, on_hand=0, allocated=0)
        initial_available = _d(inv.on_hand) - _d(inv.allocated)
        total_in_transit = sum(daily_receipts.values())
        timeline: list[dict[str, Any]] = []
        cumulative_demand = Decimal(0)
        cumulative_receipts = Decimal(0)
        max_gap = Decimal(0)
        first_shortage: Optional[str] = None
        peak_shortage: Optional[str] = None
        demand_at_peak = Decimal(0)
        available_at_peak = initial_available

        for offset in range(config.horizon_days):
            day = _day_str(start + timedelta(days=offset))
            day_demand = daily_demand.get(day, Decimal(0))
            day_receipt = _d(daily_receipts.get(day, 0))
            cumulative_demand += day_demand
            cumulative_receipts += day_receipt
            available = initial_available + cumulative_receipts
            gap = max(Decimal(0), cumulative_demand - available)
            if gap > 0 and first_shortage is None:
                first_shortage = day
            if gap > max_gap:
                max_gap = gap
                peak_shortage = day
                demand_at_peak = cumulative_demand
                available_at_peak = available
            timeline.append(
                {
                    "date": day,
                    "demand": _decimal_number(day_demand),
                    "receipt": int(day_receipt),
                    "cumulative_demand": _decimal_number(cumulative_demand),
                    "available_supply": _decimal_number(available),
                    "net_gap": _decimal_number(gap),
                }
            )

        if legacy:
            available_at_peak = initial_available + _d(total_in_transit)
            max_gap = max(Decimal(0), total_demand - available_at_peak)
            peak_shortage = window_end_s if max_gap > 0 else None
            first_shortage = need_by.get(pid) if max_gap > 0 else None
            demand_at_peak = total_demand
        elif max_gap == 0:
            available_at_peak = initial_available + _d(total_in_transit)
            demand_at_peak = total_demand

        candidates = sorted(
            supplier_by_part.get(pid, []), key=lambda row: row.supplier_id
        )
        base_qty = _ceil_decimal(max_gap * (Decimal(1) + _d(config.safety_factor)))
        candidate_rows: list[dict[str, Any]] = []
        notes: list[str] = []
        target_date = first_shortage or need_by.get(pid)
        for candidate in candidates:
            reasons: list[str] = []
            if candidate.status != 1:
                reasons.append("合作状态非合作中")
            if candidate.credit_rating not in config.allowed_ratings:
                reasons.append(f"信用等级{candidate.credit_rating}不在允许集")
            arrive = start + timedelta(days=max(0, candidate.lead_time_days))
            if target_date and arrive > _parse_day(target_date):
                reasons.append(f"交期不可达(as_of+{candidate.lead_time_days}d>{target_date})")
            if legacy:
                proposed = _ceil_to_moq(float(base_qty), candidate.moq)
            else:
                proposed = _apply_quantity_policy(base_qty, candidate.moq, candidate.order_multiple)
            if candidate.max_order_qty is not None and proposed > candidate.max_order_qty:
                reasons.append(f"建议量{proposed}超过最大订购量{candidate.max_order_qty}")
            feasible = not reasons
            candidate_rows.append(
                {
                    "supplier_id": candidate.supplier_id,
                    "supplier_name": candidate.supplier_name,
                    "lead_time_days": candidate.lead_time_days,
                    "moq": candidate.moq,
                    "order_multiple": candidate.order_multiple,
                    "max_order_qty": candidate.max_order_qty,
                    "credit_rating": candidate.credit_rating,
                    "status": candidate.status,
                    "suggested_qty": proposed,
                    "feasible": feasible,
                    "reasons": reasons,
                }
            )
            if not feasible:
                notes.extend(f"{candidate.supplier_name}:{reason}" for reason in reasons)

        selectable = [row for row in candidate_rows if row["feasible"]] or candidate_rows
        selected = min(
            selectable,
            key=lambda row: (row["suggested_qty"], row["lead_time_days"], row["supplier_id"]),
            default=None,
        )
        if max_gap <= 0:
            suggested = 0
            constraints_ok = True
        elif selected:
            suggested = int(selected["suggested_qty"])
            constraints_ok = bool(selected["feasible"])
        else:
            suggested = base_qty
            constraints_ok = False
            notes.append("无供应商采购约束数据")

        late_in_transit = 0
        if first_shortage:
            late_in_transit = sum(
                max(0, po.quantity - po.received_qty)
                for po in active_receipts.get(pid, [])
                if po.expected_date[:10] > first_shortage
            )
        evidence = [
            f"bom:{bline.bom_version or config.vehicle_model}:{pid}",
            f"as_of:{config.as_of}",
            f"window_end:{window_end_s}",
        ]
        evidence.extend(f"inventory:{ref}" for ref in inventory_refs.get(pid, []))
        evidence.extend(f"plan:{ref}" for ref in plan_refs.get(pid, []))
        evidence.extend(f"po:{ref}" for ref in transit_refs.get(pid, []))
        price_ref = bline.price_ref or f"part:{pid}:purchase_price"
        evidence.append(f"price:{price_ref}")
        purchase_price = _d(bline.purchase_price)
        selected_moq = int(selected["moq"]) if selected else 1
        selected_multiple = int(selected["order_multiple"]) if selected else 1

        lines.append(
            GapLine(
                part_id=pid,
                part_code=bline.part_code,
                part_name=bline.part_name,
                unit=bline.unit,
                demand_qty=_decimal_number(total_demand),
                on_hand=inv.on_hand,
                in_transit=total_in_transit,
                allocated=inv.allocated,
                supply_qty=_decimal_number(available_at_peak),
                net_gap=_decimal_number(max_gap),
                suggested_qty=suggested,
                need_by_date=need_by.get(pid),
                purchase_price=float(purchase_price),
                gap_amount=_money(max_gap * purchase_price),
                suggested_amount=_money(_d(suggested) * purchase_price),
                candidate_suppliers=candidate_rows,
                constraints_ok=constraints_ok,
                constraint_notes=notes if max_gap > 0 and not constraints_ok else [],
                evidence_refs=evidence,
                base_qty=base_qty,
                moq=selected_moq,
                order_multiple=selected_multiple,
                selected_supplier_id=selected["supplier_id"] if selected else None,
                selected_supplier_name=selected["supplier_name"] if selected else "",
                first_shortage_date=first_shortage,
                peak_shortage_date=peak_shortage,
                demand_at_peak=_decimal_number(demand_at_peak),
                available_at_peak=_decimal_number(available_at_peak),
                late_in_transit=late_in_transit,
                shortage_risk=_risk_level(config.as_of, first_shortage, constraints_ok),
                timeline=timeline,
                price_ref=price_ref,
            )
        )

    demand_parts = [line for line in lines if line.demand_qty > 0]
    kit_ok = [line for line in demand_parts if line.net_gap == 0]
    kit_rate = round(len(kit_ok) / len(demand_parts), 4) if demand_parts else None
    gap_parts = [line for line in lines if line.net_gap > 0]
    shortage_dates = [line.first_shortage_date for line in gap_parts if line.first_shortage_date]
    result = CalcResult(
        calc_run_id=calc_run_id or str(uuid.uuid4()),
        caliber_version=config.caliber_version,
        engine_version=ENGINE_VERSION,
        vehicle_model=config.vehicle_model,
        plant_id=config.plant_id,
        as_of=config.as_of,
        horizon_days=config.horizon_days,
        safety_factor=config.safety_factor,
        lines=lines,
        kit_rate=kit_rate,
        earliest_shortage_date=min(shortage_dates) if shortage_dates else None,
        total_gap_amount=_money(sum((_d(line.gap_amount) for line in lines), Decimal(0))),
        total_suggested_amount=_money(sum((_d(line.suggested_amount) for line in lines), Decimal(0))),
        gap_part_count=len(gap_parts),
        demand_part_count=len(demand_parts),
        input_snapshot_id=snapshot.input_snapshot_id,
        input_hash=snapshot.input_hash,
        validation_warnings=all_warnings,
        input_snapshot=snapshot,
    )
    return finalize_result(result)
