"""不可变计算记录、摘要与回放支持。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .schemas import (
    BomLine,
    CalcConfig,
    CalcRecord,
    CalcResult,
    InputSnapshot,
    InventoryLine,
    OpenPoLine,
    PlanLine,
    SupplierConstraint,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_input_snapshot(
    *,
    config: CalcConfig,
    bom: Iterable[BomLine],
    plans: Iterable[PlanLine],
    inventory: Iterable[InventoryLine],
    open_pos: Iterable[OpenPoLine],
    suppliers: Iterable[SupplierConstraint],
    source_versions: Optional[dict[str, Any]] = None,
    source_read_times: Optional[dict[str, str]] = None,
    captured_at: Optional[str] = None,
) -> InputSnapshot:
    core = {
        "config": asdict(config),
        "bom": sorted(
            (asdict(row) for row in bom),
            key=lambda row: (row["part_id"], row["part_code"], row["qty_per_vehicle"]),
        ),
        "plans": sorted(
            (asdict(row) for row in plans),
            key=lambda row: (row["plan_date"], row["plan_id"]),
        ),
        "inventory": sorted(
            (asdict(row) for row in inventory),
            key=lambda row: (row["part_id"], row.get("inventory_id") or -1),
        ),
        "open_pos": sorted(
            (asdict(row) for row in open_pos),
            key=lambda row: (row["part_id"], row["expected_date"], row["order_number"]),
        ),
        "suppliers": sorted(
            (asdict(row) for row in suppliers),
            key=lambda row: (row["part_id"], row["supplier_id"]),
        ),
        "source_versions": dict(source_versions or {}),
    }
    input_hash = sha256_digest(core)
    return InputSnapshot(
        input_snapshot_id=f"snap-{input_hash.split(':', 1)[1][:24]}",
        input_hash=input_hash,
        captured_at=captured_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_versions=core["source_versions"],
        source_read_times=dict(source_read_times or {}),
        config=core["config"],
        bom=tuple(core["bom"]),
        plans=tuple(core["plans"]),
        inventory=tuple(core["inventory"]),
        open_pos=tuple(core["open_pos"]),
        suppliers=tuple(core["suppliers"]),
    )


def result_digest(result: CalcResult | dict[str, Any]) -> str:
    payload = result.to_dict(include_input_snapshot=False) if isinstance(result, CalcResult) else dict(result)
    payload.pop("result_hash", None)
    payload.pop("input_snapshot", None)
    return sha256_digest(payload)


def finalize_result(result: CalcResult) -> CalcResult:
    result.result_hash = result_digest(result)
    return result


def build_calc_record(result: CalcResult) -> CalcRecord:
    if result.input_snapshot is None:
        raise ValueError("CalcResult 缺少 input_snapshot，不能建立可回放记录")
    if not result.result_hash:
        finalize_result(result)
    result_payload = result.to_dict(include_input_snapshot=False)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record_core = {
        "calc_run_id": result.calc_run_id,
        "caliber_version": result.caliber_version,
        "engine_version": result.engine_version,
        "input_hash": result.input_hash,
        "result_hash": result.result_hash,
    }
    return CalcRecord(
        calc_run_id=result.calc_run_id,
        caliber_version=result.caliber_version,
        engine_version=result.engine_version,
        input_snapshot_id=result.input_snapshot_id,
        input_hash=result.input_hash,
        result_hash=result.result_hash,
        record_hash=sha256_digest(record_core),
        status=result.status,
        created_at=created_at,
        input_snapshot=result.input_snapshot.to_dict(),
        result=result_payload,
    )


def replay_calc_record(record: CalcRecord | dict[str, Any]) -> dict[str, Any]:
    """用历史输入重算并精确比较摘要；不会读取当前 ERP 数据。"""

    raw = record.to_dict() if isinstance(record, CalcRecord) else dict(record)
    snap = raw["input_snapshot"]
    config_raw = dict(snap["config"])
    if isinstance(config_raw.get("allowed_ratings"), list):
        config_raw["allowed_ratings"] = tuple(config_raw["allowed_ratings"])
    config = CalcConfig(**config_raw)

    from .engine import run_shortage_calc

    replayed = run_shortage_calc(
        config=config,
        bom=[BomLine(**row) for row in snap["bom"]],
        plans=[PlanLine(**row) for row in snap["plans"]],
        inventory=[InventoryLine(**row) for row in snap["inventory"]],
        open_pos=[OpenPoLine(**row) for row in snap["open_pos"]],
        suppliers=[SupplierConstraint(**row) for row in snap["suppliers"]],
        calc_run_id=str(raw["calc_run_id"]),
        source_versions=dict(snap.get("source_versions") or {}),
        source_read_times=dict(snap.get("source_read_times") or {}),
        captured_at=snap.get("captured_at"),
    )
    return {
        "matched": replayed.result_hash == raw.get("result_hash"),
        "expected_result_hash": raw.get("result_hash"),
        "actual_result_hash": replayed.result_hash,
        "result": replayed.to_dict(),
    }


CALC_NAMESPACE = "shortage-calculations"


def persist_calc_record(store: Any, user_id: str, record: CalcRecord | dict[str, Any]) -> None:
    """利用现有 LangGraph Store 保存不可变记录，不引入新基础设施。"""

    if store is None:
        return
    value = record.to_dict() if isinstance(record, CalcRecord) else dict(record)
    key = str(value["calc_run_id"])
    namespace = (CALC_NAMESPACE, str(user_id or "default_user"))
    if hasattr(store, "put_immutable"):
        store.put_immutable(namespace, key, value, identity_field="record_hash")
        return
    existing = store.get(namespace, key)
    if existing is not None:
        old = getattr(existing, "value", existing)
        if isinstance(old, dict) and old.get("record_hash") == value.get("record_hash"):
            return
        raise ValueError(f"calc_run_id={key} 已存在且内容摘要不同，拒绝覆盖")
    store.put(namespace, key, value)


def load_calc_record(store: Any, user_id: str, calc_run_id: str) -> Optional[dict[str, Any]]:
    if store is None or not calc_run_id:
        return None
    item = store.get((CALC_NAMESPACE, str(user_id or "default_user")), str(calc_run_id))
    if item is None:
        return None
    value = getattr(item, "value", item)
    return dict(value) if isinstance(value, dict) else None


def load_calc_result(store: Any, user_id: str, calc_run_id: str) -> Optional[dict[str, Any]]:
    record = load_calc_record(store, user_id, calc_run_id)
    return dict(record["result"]) if record and isinstance(record.get("result"), dict) else None
