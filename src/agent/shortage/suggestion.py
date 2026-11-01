"""缺料采购建议固化：审批内容摘要、过期控制与强一致写前校验。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_digest(payload: dict[str, Any]) -> str:
    value = dict(payload)
    value.pop("payloadHash", None)
    value.pop("idempotencyKey", None)
    value.pop("idempotency_key", None)
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _action_digest(payload: dict[str, Any]) -> str:
    """同一计算建议的稳定业务摘要，不受冻结时间和展示订单号影响。"""

    value = dict(payload)
    for field in ("payloadHash", "idempotencyKey", "idempotency_key", "frozenAt", "expiresAt", "orderNumber"):
        value.pop(field, None)
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _gen_order_number(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8].upper()
    return f"PO{datetime.now().strftime('%Y%m%d')}{digest}"


def freeze_shortage_suggestion(
    calc: dict[str, Any],
    *,
    only_gap_parts: bool = True,
    only_feasible: bool = True,
    remark: str = "",
    valid_for_minutes: int = 1440,
) -> dict[str, Any]:
    """将 CalcResult 固化为审批/建单 payload。

    行、工厂、供应商、价格来源和数量全部取自同一计算记录。无可行供应商的行默认
    作为 ``blocked_lines`` 返回，不会混入待审批订单。
    """

    if not isinstance(calc, dict) or not calc.get("calc_run_id"):
        raise ValueError("calc 须为含 calc_run_id 的 CalcResult")
    if not calc.get("caliber_version"):
        raise ValueError("calc 缺少 caliber_version")
    if calc.get("status", "succeeded") != "succeeded":
        raise ValueError("只有 succeeded 的计算记录可以固化采购建议")

    calc_run_id = str(calc["calc_run_id"])
    caliber = str(calc["caliber_version"])
    suggestion_id = f"sug-{calc_run_id[:12]}"
    frozen_at_dt = datetime.now(timezone.utc)
    expires_at_dt = frozen_at_dt + timedelta(minutes=max(1, int(valid_for_minutes)))
    frozen_at = frozen_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = expires_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    details: list[dict[str, Any]] = []
    blocked_lines: list[dict[str, Any]] = []
    for line in calc.get("lines") or []:
        qty = int(line.get("suggested_qty") or 0)
        gap = float(line.get("net_gap") or 0)
        if only_gap_parts and (qty <= 0 or gap <= 0):
            continue
        if only_feasible and line.get("constraints_ok") is False:
            blocked_lines.append(
                {
                    "part_id": line.get("part_id"),
                    "part_code": line.get("part_code"),
                    "suggested_qty": qty,
                    "reasons": list(line.get("constraint_notes") or []),
                }
            )
            continue
        price = float(line.get("purchase_price") or 0)
        details.append(
            {
                "partId": int(line["part_id"]),
                "quantity": qty,
                "unit": line.get("unit") or "",
                "unitPrice": price,
                "priceRef": line.get("price_ref") or "",
                "supplierId": line.get("selected_supplier_id"),
                "remark": (
                    f"calc={calc_run_id};gap={line.get('net_gap')};"
                    f"part={line.get('part_code') or line.get('part_id')}"
                ),
            }
        )

    if not details:
        if blocked_lines:
            raise ValueError("所有缺料行均不满足供应商/交期约束，禁止自动建单")
        raise ValueError("无建议采购行（suggested_qty 全为 0），无需建单")

    total = float(sum(Decimal(str(row["quantity"])) * Decimal(str(row["unitPrice"])) for row in details).quantize(Decimal("0.01")))
    order_payload: dict[str, Any] = {
        "orderNumber": "",
        "totalAmount": total,
        "status": 0,
        "remark": remark
        or (
            f"缺料补货 suggestion={suggestion_id} "
            f"vehicle={calc.get('vehicle_model')} plant={calc.get('plant_id')}"
        ),
        "vehicleModel": calc.get("vehicle_model"),
        "plantId": calc.get("plant_id"),
        "orderDetail": details,
        "calc_run_id": calc_run_id,
        "input_snapshot_id": calc.get("input_snapshot_id"),
        "input_hash": calc.get("input_hash"),
        "result_hash": calc.get("result_hash"),
        "suggestion_id": suggestion_id,
        "caliber_version": caliber,
        "frozenAt": frozen_at,
        "expiresAt": expires_at,
    }
    # 订单号与幂等键都由冻结内容导出；审批后重建会得到同一业务键。
    preliminary_hash = _action_digest(order_payload)
    idempotency_key = f"shortage:{calc_run_id}:{preliminary_hash.split(':', 1)[1][:16]}"
    order_payload["idempotencyKey"] = idempotency_key
    order_payload["orderNumber"] = _gen_order_number(idempotency_key)
    payload_hash = _payload_digest(order_payload)
    order_payload["payloadHash"] = payload_hash

    return {
        "status": "PENDING_APPROVAL",
        "suggestion_id": suggestion_id,
        "idempotency_key": idempotency_key,
        "calc_run_id": calc_run_id,
        "caliber_version": caliber,
        "frozen_at": frozen_at,
        "expires_at": expires_at,
        "payload_hash": payload_hash,
        "vehicle_model": calc.get("vehicle_model"),
        "plant_id": calc.get("plant_id"),
        "line_count": len(details),
        "total_amount": total,
        "blocked_lines": blocked_lines,
        "order_payload": order_payload,
    }


def validate_order_create_payload(
    data: dict[str, Any], *, now: Optional[datetime] = None
) -> list[str]:
    """写前细字段与冻结摘要校验；返回错误列表（空=通过）。"""

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
        if declared_total.quantize(Decimal("0.01")) != computed_total.quantize(Decimal("0.01")):
            errors.append(f"totalAmount {declared_total} 与明细合计 {computed_total} 不一致")
    except (TypeError, ValueError, ArithmeticError):
        errors.append("totalAmount 须为数字")

    shortage_path = data.get("suggestion_id") or str(data.get("idempotencyKey") or "").startswith("shortage:")
    if shortage_path:
        for field, label in (
            ("calc_run_id", "calc_run_id"),
            ("idempotencyKey", "idempotencyKey"),
            ("payloadHash", "payloadHash"),
            ("caliber_version", "caliber_version"),
            ("vehicleModel", "vehicleModel"),
            ("plantId", "plantId"),
            ("expiresAt", "expiresAt"),
        ):
            if not data.get(field):
                errors.append(f"缺料写回须带 {label}")
        if data.get("payloadHash") and data["payloadHash"] != _payload_digest(data):
            errors.append("payloadHash 与当前订单内容不一致，审批后载荷可能被篡改")
        if data.get("expiresAt"):
            try:
                expires = datetime.fromisoformat(str(data["expiresAt"]).replace("Z", "+00:00"))
                current = now or datetime.now(timezone.utc)
                if current.tzinfo is None:
                    current = current.replace(tzinfo=timezone.utc)
                if current > expires:
                    errors.append("固化采购建议已过期，须重新计算并重新审批")
            except ValueError:
                errors.append("expiresAt 不是有效 ISO 时间")
    return errors


def assert_payload_matches_calc(
    order_data: dict[str, Any],
    calc: Optional[dict[str, Any]],
) -> list[str]:
    """订单的范围、完整行集、数量、价格来源及供应商须与 calc 精确一致。"""

    errors: list[str] = []
    if not calc:
        if order_data.get("calc_run_id"):
            errors.append(f"找不到 calc_run_id={order_data.get('calc_run_id')} 的计算快照")
        return errors
    for payload_key, calc_key, label in (
        ("calc_run_id", "calc_run_id", "计算批次"),
        ("caliber_version", "caliber_version", "计算口径"),
        ("vehicleModel", "vehicle_model", "车型"),
        ("plantId", "plant_id", "工厂"),
        ("input_snapshot_id", "input_snapshot_id", "输入快照"),
        ("input_hash", "input_hash", "输入摘要"),
        ("result_hash", "result_hash", "结果摘要"),
    ):
        expected = calc.get(calc_key)
        actual = order_data.get(payload_key)
        if expected and str(actual or "") != str(expected):
            errors.append(f"{label} {actual!r} ≠ calc.{calc_key} {expected!r}")

    by_part = {
        int(line["part_id"]): line
        for line in (calc.get("lines") or [])
        if line.get("part_id") is not None
    }
    expected_parts = {
        part_id
        for part_id, line in by_part.items()
        if int(line.get("suggested_qty") or 0) > 0
        and float(line.get("net_gap") or 0) > 0
        and line.get("constraints_ok", True) is not False
    }
    actual_parts: set[int] = set()
    for index, row in enumerate(order_data.get("orderDetail") or []):
        try:
            part_id = int(row["partId"])
        except (KeyError, TypeError, ValueError):
            continue
        actual_parts.add(part_id)
        line = by_part.get(part_id)
        if not line:
            errors.append(f"orderDetail[{index}].partId={part_id} 不在 calc 结果中")
            continue
        expected_qty = int(line.get("suggested_qty") or 0)
        actual_qty = int(row.get("quantity") or 0)
        if actual_qty != expected_qty:
            errors.append(f"orderDetail[{index}] 数量 {actual_qty} ≠ calc.suggested_qty {expected_qty}")
        expected_price = Decimal(str(line.get("purchase_price") or 0))
        actual_price = Decimal(str(row.get("unitPrice") or 0))
        if actual_price != expected_price:
            errors.append(f"orderDetail[{index}] 单价 {actual_price} ≠ calc.purchase_price {expected_price}")
        expected_supplier = line.get("selected_supplier_id")
        if expected_supplier is not None and row.get("supplierId") != expected_supplier:
            errors.append(f"orderDetail[{index}] 供应商 {row.get('supplierId')} ≠ calc.selected_supplier_id {expected_supplier}")
        expected_unit = line.get("unit") or ""
        if expected_unit and row.get("unit") != expected_unit:
            errors.append(f"orderDetail[{index}] 单位 {row.get('unit')} ≠ calc.unit {expected_unit}")
        expected_price_ref = line.get("price_ref") or ""
        if expected_price_ref and row.get("priceRef") != expected_price_ref:
            errors.append(f"orderDetail[{index}] 价格来源与 calc 不一致")
    if actual_parts != expected_parts:
        missing = sorted(expected_parts - actual_parts)
        extra = sorted(actual_parts - expected_parts)
        if missing:
            errors.append(f"采购明细缺少已固化建议物料: {missing}")
        if extra:
            errors.append(f"采购明细包含未获准物料: {extra}")
    return errors


def parse_order_data_arg(raw: Any) -> dict[str, Any]:
    """解析 order_create 的 order_data 参数。"""

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
