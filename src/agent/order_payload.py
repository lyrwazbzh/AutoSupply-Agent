"""采购订单写前载荷解析与基础字段校验。"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def parse_order_data_arg(raw: Any) -> dict[str, Any]:
    """解析 order_create / order_update 的 order_data 参数。"""

    if isinstance(raw, dict):
        if "order_payload" in raw and isinstance(raw["order_payload"], dict):
            return raw["order_payload"]
        return raw
    if isinstance(raw, str):
        data = json.loads(raw)
        if isinstance(data, dict) and "order_payload" in data:
            return data["order_payload"]
        if isinstance(data, dict):
            return data
    raise ValueError("order_data 无法解析为对象")


def validate_order_create_payload(data: dict[str, Any]) -> list[str]:
    """写前明细与金额校验；返回错误列表（空 = 通过）。"""

    errors: list[str] = []
    if not isinstance(data, dict):
        return ["order_data 须为对象"]
    details = data.get("orderDetail")
    if not isinstance(details, list) or not details:
        return ["orderDetail 至少一条明细"]

    seen_parts: set[int] = set()
    computed_total = Decimal(0)
    for index, row in enumerate(details):
        if not isinstance(row, dict):
            errors.append(f"orderDetail[{index}] 须为对象")
            continue
        try:
            part_id = int(row.get("partId"))
            if part_id <= 0:
                raise ValueError
            if part_id in seen_parts:
                errors.append(f"orderDetail[{index}].partId={part_id} 重复")
            seen_parts.add(part_id)
        except (TypeError, ValueError):
            errors.append(f"orderDetail[{index}].partId 须为正整数")
        try:
            qty = int(row.get("quantity"))
            if qty < 1 or qty != float(row.get("quantity")):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"orderDetail[{index}].quantity 须为 >= 1 的整数")
            qty = 0
        try:
            price = Decimal(str(row.get("unitPrice")))
            if not price.is_finite() or price <= 0:
                raise ValueError
        except (TypeError, ValueError, ArithmeticError):
            errors.append(f"orderDetail[{index}].unitPrice 须为正数")
            price = Decimal(0)
        computed_total += Decimal(qty) * price

    try:
        declared_total = Decimal(str(data.get("totalAmount")))
        if declared_total.quantize(Decimal("0.01")) != computed_total.quantize(
            Decimal("0.01")
        ):
            errors.append(
                f"totalAmount {declared_total} 与明细合计 {computed_total} 不一致"
            )
    except (TypeError, ValueError, ArithmeticError):
        errors.append("totalAmount 须为数字")

    return errors
