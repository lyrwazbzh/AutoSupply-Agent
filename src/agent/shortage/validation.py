"""缺料输入业务校验。非法数据在进入公式前显式失败。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .schemas import (
    BomLine,
    CalcConfig,
    InventoryLine,
    OpenPoLine,
    PlanLine,
    SupplierConstraint,
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


class InputValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


def _valid_day(value: str) -> bool:
    try:
        datetime.strptime(str(value)[:10], "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def _finite_non_negative(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0


def validate_shortage_inputs(
    *,
    config: CalcConfig,
    bom: Iterable[BomLine],
    plans: Iterable[PlanLine],
    inventory: Iterable[InventoryLine],
    open_pos: Iterable[OpenPoLine],
    suppliers: Iterable[SupplierConstraint],
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """返回 ``(errors, warnings)``，不静默吞掉异常 ERP 数据。"""

    bom_rows = list(bom)
    plan_rows = list(plans)
    inventory_rows = list(inventory)
    po_rows = list(open_pos)
    supplier_rows = list(suppliers)
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    def error(code: str, field: str, message: str) -> None:
        errors.append(ValidationIssue(code, field, message))

    def warn(code: str, field: str, message: str) -> None:
        warnings.append(ValidationIssue(code, field, message, "warning"))

    if not str(config.vehicle_model).strip():
        error("missing_scope", "vehicle_model", "vehicle_model 不能为空")
    if not str(config.plant_id).strip():
        error("missing_scope", "plant_id", "plant_id 不能为空")
    if not _valid_day(config.as_of):
        error("invalid_date", "as_of", f"as_of 日期无效: {config.as_of}")
    if not isinstance(config.horizon_days, int) or config.horizon_days < 1:
        error("invalid_horizon", "horizon_days", "horizon_days 须为正整数")
    if not _finite_non_negative(config.safety_factor):
        error("invalid_safety_factor", "safety_factor", "safety_factor 须为非负有限数")
    if not bom_rows:
        error("empty_bom", "bom", "BOM 不能为空")

    bom_meta: dict[int, BomLine] = {}
    for index, row in enumerate(bom_rows):
        prefix = f"bom[{index}]"
        if not isinstance(row.part_id, int) or row.part_id <= 0:
            error("invalid_part", f"{prefix}.part_id", "BOM part_id 须为正整数")
        if not _finite_non_negative(row.qty_per_vehicle) or float(row.qty_per_vehicle) <= 0:
            error("invalid_quantity", f"{prefix}.qty_per_vehicle", "BOM 单车用量须大于 0")
        if not _finite_non_negative(row.purchase_price):
            error("invalid_price", f"{prefix}.purchase_price", "采购价不能为负数或非有限数")
        previous = bom_meta.get(row.part_id)
        if previous and any(
            left and right and str(left).strip().lower() != str(right).strip().lower()
            for left, right in (
                (previous.unit, row.unit),
                (previous.part_code, row.part_code),
                (previous.bom_version, row.bom_version),
            )
        ):
            error("conflicting_bom_duplicate", prefix, f"物料 {row.part_id} 的重复 BOM 行元数据冲突")
        if previous and float(previous.purchase_price) != float(row.purchase_price):
            error("conflicting_bom_duplicate", prefix, f"物料 {row.part_id} 的重复 BOM 行采购价冲突")
        bom_meta.setdefault(row.part_id, row)

    plan_ids: set[str] = set()
    for index, row in enumerate(plan_rows):
        prefix = f"plans[{index}]"
        if not row.plan_id:
            error("missing_plan_id", f"{prefix}.plan_id", "生产计划行缺少 plan_id")
        elif row.plan_id in plan_ids:
            error("duplicate_plan", f"{prefix}.plan_id", f"重复生产计划行: {row.plan_id}")
        plan_ids.add(row.plan_id)
        if not _valid_day(row.plan_date):
            error("invalid_date", f"{prefix}.plan_date", f"生产计划日期无效: {row.plan_date}")
        if not isinstance(row.quantity, int) or row.quantity < 0:
            error("invalid_quantity", f"{prefix}.quantity", "生产计划数量须为非负整数")

    for index, row in enumerate(inventory_rows):
        prefix = f"inventory[{index}]"
        if row.part_id not in bom_meta:
            error("unknown_part", f"{prefix}.part_id", f"库存物料 {row.part_id} 不在 BOM 中")
        if row.status.lower() not in ("available", "可用"):
            warn("inventory_unavailable", prefix, f"库存记录 {row.inventory_id} 状态不可用，将不计入供给")
        if not isinstance(row.on_hand, int) or row.on_hand < 0:
            error("invalid_quantity", f"{prefix}.on_hand", "现有库存须为非负整数")
        if not isinstance(row.allocated, int) or row.allocated < 0:
            error("invalid_quantity", f"{prefix}.allocated", "已分配量须为非负整数")
        if row.allocated > row.on_hand:
            error(
                "allocation_exceeds_on_hand",
                prefix,
                f"物料 {row.part_id} 已分配量 {row.allocated} 超过现有库存 {row.on_hand}，需核对 ERP 口径",
            )
        bom_unit = bom_meta.get(row.part_id).unit if row.part_id in bom_meta else ""
        if row.unit and bom_unit and row.unit.lower() != bom_unit.lower():
            error("unit_mismatch", f"{prefix}.unit", f"物料 {row.part_id} 库存单位 {row.unit} 与 BOM 单位 {bom_unit} 不一致")

    po_keys: set[tuple[str, int]] = set()
    for index, row in enumerate(po_rows):
        prefix = f"open_pos[{index}]"
        if row.part_id not in bom_meta:
            error("unknown_part", f"{prefix}.part_id", f"在途物料 {row.part_id} 不在 BOM 中")
        if not isinstance(row.quantity, int) or row.quantity < 0:
            error("invalid_quantity", f"{prefix}.quantity", "在途数量须为非负整数")
        if not isinstance(row.received_qty, int) or row.received_qty < 0 or row.received_qty > row.quantity:
            error("invalid_received_qty", f"{prefix}.received_qty", "已收货量须介于 0 与订单数量之间")
        if not _valid_day(row.expected_date):
            error("invalid_date", f"{prefix}.expected_date", f"预计到货日期无效: {row.expected_date}")
        elif _valid_day(config.as_of) and row.expected_date[:10] < config.as_of[:10] and row.order_status in (1, 2):
            warn("overdue_receipt", prefix, f"订单 {row.order_number or index} 已逾期，不能自动视为可用库存")
        key = (row.order_number, row.part_id)
        if row.order_number and key in po_keys:
            error("duplicate_open_po", prefix, f"重复在途订单行: {row.order_number}/物料{row.part_id}")
        po_keys.add(key)
        bom_unit = bom_meta.get(row.part_id).unit if row.part_id in bom_meta else ""
        if row.unit and bom_unit and row.unit.lower() != bom_unit.lower():
            error("unit_mismatch", f"{prefix}.unit", f"物料 {row.part_id} 在途单位 {row.unit} 与 BOM 单位 {bom_unit} 不一致")

    for index, row in enumerate(supplier_rows):
        prefix = f"suppliers[{index}]"
        if row.part_id not in bom_meta:
            error("unknown_part", f"{prefix}.part_id", f"供应商约束物料 {row.part_id} 不在 BOM 中")
        if row.lead_time_days < 0:
            error("invalid_lead_time", f"{prefix}.lead_time_days", "交期天数不能为负")
        if row.moq < 1:
            error("invalid_moq", f"{prefix}.moq", "MOQ 须至少为 1")
        if row.order_multiple < 1:
            error("invalid_order_multiple", f"{prefix}.order_multiple", "包装/订购倍数须至少为 1")
        if row.max_order_qty is not None and row.max_order_qty < row.moq:
            error("invalid_max_order", f"{prefix}.max_order_qty", "最大订购量不能小于 MOQ")

    return errors, warnings
