"""
缺料演示种子（车型 A-125 / PLANT-HZ）

与 docs/shortage-口径.md、test_shortage_engine 金标对齐。
part_id 对齐 erp_mock_server 主种子零部件序号。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

VEHICLE_MODEL = "A-125"
PLANT_ID = "PLANT-HZ"
BOM_VERSION = "A-125-BOM-v1"

# part_id → 单车用量（对齐 _PART_SEED 序号）
# 1 火花塞 / 7 前刹车片 / 12 蓄电池 / 4 曲轴总成 / 18 驱动链条
BOM_ROWS: list[dict[str, Any]] = [
    {"partId": 1, "qtyPerVehicle": 4, "partCode": "P-EN-0001", "partName": "火花塞"},
    {"partId": 7, "qtyPerVehicle": 1, "partCode": "P-BR-0001", "partName": "前刹车片"},
    {"partId": 12, "qtyPerVehicle": 1, "partCode": "P-EL-0001", "partName": "蓄电池"},
    {"partId": 4, "qtyPerVehicle": 1, "partCode": "P-EN-0004", "partName": "曲轴总成"},
    {"partId": 18, "qtyPerVehicle": 1, "partCode": "P-DR-0001", "partName": "驱动链条"},
]

# 覆盖库存：制造可手算缺口（allocated 默认 0）
INVENTORY_OVERRIDE: dict[int, int] = {
    1: 50,    # 火花塞：需求 400，在途 100 → 供给 150 → 缺口 250
    7: 120,   # 前刹车片：需求 100，在途 0 → 齐套
    12: 20,   # 蓄电池：需求 100，在途 30 → 缺口 50
    4: 10,    # 曲轴：需求 100，在途 0 → 缺口 90
    18: 200,  # 驱动链：需求 100 → 齐套
}

# MOQ 是最低采购量，orderMultiple 是独立的包装/订购倍数。
PROCUREMENT_PROFILE: dict[int, dict[str, int]] = {
    1: {"leadTimeDays": 1, "moq": 50, "orderMultiple": 50},
    7: {"leadTimeDays": 5, "moq": 20, "orderMultiple": 20},
    12: {"leadTimeDays": 1, "moq": 10, "orderMultiple": 10},
    4: {"leadTimeDays": 14, "moq": 5, "orderMultiple": 5},
    18: {"leadTimeDays": 4, "moq": 10, "orderMultiple": 10},
}


def build_plans(as_of: datetime) -> list[dict[str, Any]]:
    """窗口内合计 100 台：D+1 打 40，D+3 打 60。"""
    d1 = (as_of + timedelta(days=1)).strftime("%Y-%m-%d")
    d3 = (as_of + timedelta(days=3)).strftime("%Y-%m-%d")
    return [
        {
            "planId": "PLAN-A125-001",
            "vehicleModel": VEHICLE_MODEL,
            "plantId": PLANT_ID,
            "planDate": d1,
            "quantity": 40,
        },
        {
            "planId": "PLAN-A125-002",
            "vehicleModel": VEHICLE_MODEL,
            "plantId": PLANT_ID,
            "planDate": d3,
            "quantity": 60,
        },
    ]


def build_open_pos(as_of: datetime) -> list[dict[str, Any]]:
    """在途：火花塞 100（已发货）、蓄电池 30（已审核）。"""
    e2 = (as_of + timedelta(days=2)).strftime("%Y-%m-%d")
    e4 = (as_of + timedelta(days=4)).strftime("%Y-%m-%d")
    return [
        {
            "orderNumber": "PO-TRANSIT-SPARK",
            "partId": 1,
            "quantity": 100,
            "expectedDate": e2,
            "status": 2,
        },
        {
            "orderNumber": "PO-TRANSIT-BATT",
            "partId": 12,
            "quantity": 30,
            "expectedDate": e4,
            "status": 1,
        },
    ]


def golden_demand() -> dict[int, float]:
    """100 台 × BOM。"""
    return {row["partId"]: 100 * row["qtyPerVehicle"] for row in BOM_ROWS}


def golden_gaps() -> dict[int, float]:
    """
    demand - max(0, on_hand + in_transit - allocated)
    火花塞 400-150=250；刹车片 0；蓄电池 100-50=50；曲轴 100-10=90；链条 0
    """
    transit = {1: 100, 12: 30}
    gaps: dict[int, float] = {}
    for pid, dem in golden_demand().items():
        supply = max(0, INVENTORY_OVERRIDE[pid] + transit.get(pid, 0))
        gaps[pid] = max(0.0, dem - supply)
    return gaps


def golden_gaps_v2() -> dict[int, float]:
    """按日累计供需峰值。蓄电池 D+4 才到，在 D+3 形成 80 件峰值缺口。"""

    return {1: 250.0, 7: 0.0, 12: 80.0, 4: 90.0, 18: 0.0}
