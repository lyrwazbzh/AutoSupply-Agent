"""零部件缺料确定性计算与建议固化（shortage_engine / M2）。"""

from .actions import (
    load_procurement_action,
    persist_frozen_suggestion,
    validate_frozen_suggestion,
)
from .engine import run_shortage_calc
from .records import build_calc_record, replay_calc_record
from .report import build_verified_facts, render_verified_summary
from .schemas import (
    CALIBER_VERSION,
    ENGINE_VERSION,
    LEGACY_CALIBER_VERSION,
    BomLine,
    CalcConfig,
    CalcRecord,
    CalcResult,
    GapLine,
    InputSnapshot,
    InventoryLine,
    OpenPoLine,
    PlanLine,
    SupplierConstraint,
)
from .suggestion import (
    assert_payload_matches_calc,
    freeze_shortage_suggestion,
    validate_order_create_payload,
)

__all__ = [
    "BomLine",
    "CALIBER_VERSION",
    "CalcConfig",
    "CalcRecord",
    "CalcResult",
    "ENGINE_VERSION",
    "GapLine",
    "InventoryLine",
    "InputSnapshot",
    "LEGACY_CALIBER_VERSION",
    "OpenPoLine",
    "PlanLine",
    "SupplierConstraint",
    "assert_payload_matches_calc",
    "build_calc_record",
    "build_verified_facts",
    "freeze_shortage_suggestion",
    "load_procurement_action",
    "persist_frozen_suggestion",
    "run_shortage_calc",
    "replay_calc_record",
    "render_verified_summary",
    "validate_order_create_payload",
    "validate_frozen_suggestion",
]
