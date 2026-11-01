"""缺料计算领域结构（v1 兼容、v2 为默认口径）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

LEGACY_CALIBER_VERSION = "shortage-口径/v1"
CALIBER_VERSION = "shortage-口径/v2"
ENGINE_VERSION = "2.0.0"


@dataclass(frozen=True)
class BomLine:
    part_id: int
    qty_per_vehicle: float
    part_code: str = ""
    part_name: str = ""
    unit: str = ""
    purchase_price: float = 0.0
    bom_version: str = ""
    price_ref: str = ""


@dataclass(frozen=True)
class PlanLine:
    plan_id: str
    vehicle_model: str
    plant_id: str
    plan_date: str  # yyyy-MM-dd
    quantity: int
    unit: str = "vehicle"


@dataclass(frozen=True)
class InventoryLine:
    part_id: int
    on_hand: int
    allocated: int = 0
    inventory_id: Optional[int] = None
    unit: str = ""
    status: str = "available"


@dataclass(frozen=True)
class OpenPoLine:
    part_id: int
    quantity: int
    expected_date: str  # yyyy-MM-dd
    order_number: str = ""
    order_status: int = 1
    unit: str = ""
    received_qty: int = 0


@dataclass(frozen=True)
class SupplierConstraint:
    part_id: int
    supplier_id: int
    supplier_name: str
    status: int
    credit_rating: str
    lead_time_days: int
    moq: int = 1
    order_multiple: int = 1
    max_order_qty: Optional[int] = None


@dataclass(frozen=True)
class CalcConfig:
    vehicle_model: str
    plant_id: str
    as_of: str
    horizon_days: int = 7
    safety_factor: float = 0.1
    allowed_ratings: tuple[str, ...] = ("A", "B")
    caliber_version: str = CALIBER_VERSION


@dataclass(frozen=True)
class InputSnapshot:
    """参与一次计算的完整、内容寻址输入快照。"""

    input_snapshot_id: str
    input_hash: str
    captured_at: str
    source_versions: dict[str, Any]
    source_read_times: dict[str, str]
    config: dict[str, Any]
    bom: tuple[dict[str, Any], ...]
    plans: tuple[dict[str, Any], ...]
    inventory: tuple[dict[str, Any], ...]
    open_pos: tuple[dict[str, Any], ...]
    suppliers: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GapLine:
    part_id: int
    part_code: str
    part_name: str
    unit: str
    demand_qty: float
    on_hand: int
    in_transit: int
    allocated: int
    supply_qty: float
    net_gap: float
    suggested_qty: int
    need_by_date: Optional[str]
    purchase_price: float
    gap_amount: float
    suggested_amount: float
    candidate_suppliers: list[dict[str, Any]] = field(default_factory=list)
    constraints_ok: bool = False
    constraint_notes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    base_qty: int = 0
    moq: int = 1
    order_multiple: int = 1
    selected_supplier_id: Optional[int] = None
    selected_supplier_name: str = ""
    first_shortage_date: Optional[str] = None
    peak_shortage_date: Optional[str] = None
    demand_at_peak: float = 0.0
    available_at_peak: float = 0.0
    late_in_transit: int = 0
    shortage_risk: str = "none"
    timeline: list[dict[str, Any]] = field(default_factory=list)
    price_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalcResult:
    calc_run_id: str
    caliber_version: str
    vehicle_model: str
    plant_id: str
    as_of: str
    horizon_days: int
    safety_factor: float
    lines: list[GapLine]
    kit_rate: Optional[float]
    total_gap_amount: float
    total_suggested_amount: float
    gap_part_count: int
    demand_part_count: int
    engine_version: str = ENGINE_VERSION
    input_snapshot_id: str = ""
    input_hash: str = ""
    result_hash: str = ""
    status: str = "succeeded"
    material_kit_rate_definition: str = "无缺口物料种数/有需求物料种数"
    earliest_shortage_date: Optional[str] = None
    validation_warnings: list[str] = field(default_factory=list)
    input_snapshot: Optional[InputSnapshot] = None

    def to_dict(self, *, include_input_snapshot: bool = True) -> dict[str, Any]:
        payload = {
            "calc_run_id": self.calc_run_id,
            "caliber_version": self.caliber_version,
            "engine_version": self.engine_version,
            "vehicle_model": self.vehicle_model,
            "plant_id": self.plant_id,
            "as_of": self.as_of,
            "horizon_days": self.horizon_days,
            "safety_factor": self.safety_factor,
            "kit_rate": self.kit_rate,
            "material_kit_rate": self.kit_rate,
            "material_kit_rate_definition": self.material_kit_rate_definition,
            "earliest_shortage_date": self.earliest_shortage_date,
            "total_gap_amount": self.total_gap_amount,
            "total_suggested_amount": self.total_suggested_amount,
            "gap_part_count": self.gap_part_count,
            "demand_part_count": self.demand_part_count,
            "input_snapshot_id": self.input_snapshot_id,
            "input_hash": self.input_hash,
            "result_hash": self.result_hash,
            "status": self.status,
            "validation_warnings": list(self.validation_warnings),
            "lines": [line.to_dict() for line in self.lines],
        }
        if include_input_snapshot and self.input_snapshot is not None:
            payload["input_snapshot"] = self.input_snapshot.to_dict()
        return payload


@dataclass(frozen=True)
class CalcRecord:
    """持久化单元：输入、结果、版本与摘要绑定在同一条不可变记录中。"""

    calc_run_id: str
    caliber_version: str
    engine_version: str
    input_snapshot_id: str
    input_hash: str
    result_hash: str
    record_hash: str
    status: str
    created_at: str
    input_snapshot: dict[str, Any]
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
