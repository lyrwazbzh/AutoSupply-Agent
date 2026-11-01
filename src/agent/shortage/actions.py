"""采购建议与派发动作在现有 Store 中的持久化状态。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

SUGGESTION_NAMESPACE = "shortage-suggestions"
ACTION_NAMESPACE = "shortage-procurement-actions"


def _value(item: Any) -> Optional[dict[str, Any]]:
    if item is None:
        return None
    value = getattr(item, "value", item)
    return dict(value) if isinstance(value, dict) else None


def _namespace(name: str, user_id: str) -> tuple[str, str]:
    return name, str(user_id or "default_user")


def persist_frozen_suggestion(store: Any, user_id: str, frozen: dict[str, Any]) -> None:
    if store is None:
        return
    key = str(frozen["suggestion_id"])
    namespace = _namespace(SUGGESTION_NAMESPACE, user_id)
    if hasattr(store, "put_immutable"):
        store.put_immutable(namespace, key, frozen, identity_field="payload_hash")
        return
    existing = _value(store.get(namespace, key))
    if existing:
        if existing.get("payload_hash") != frozen.get("payload_hash"):
            raise ValueError(f"suggestion_id={key} 已冻结为不同载荷")
        return
    store.put(namespace, key, frozen)


def load_frozen_suggestion(store: Any, user_id: str, suggestion_id: str) -> Optional[dict[str, Any]]:
    if store is None or not suggestion_id:
        return None
    return _value(store.get(_namespace(SUGGESTION_NAMESPACE, user_id), str(suggestion_id)))


def load_procurement_action(store: Any, user_id: str, idempotency_key: str) -> Optional[dict[str, Any]]:
    if store is None or not idempotency_key:
        return None
    return _value(store.get(_namespace(ACTION_NAMESPACE, user_id), str(idempotency_key)))


def validate_frozen_suggestion(
    store: Any, user_id: str, order_data: dict[str, Any]
) -> list[str]:
    """把待执行载荷与审批前冻结记录的摘要绑定。"""

    if store is None:
        return []
    suggestion_id = str(order_data.get("suggestion_id") or "")
    frozen = load_frozen_suggestion(store, user_id, suggestion_id)
    if not frozen:
        return [f"找不到 suggestion_id={suggestion_id} 的持久化冻结建议"]
    errors: list[str] = []
    if frozen.get("payload_hash") != order_data.get("payloadHash"):
        errors.append("当前 payloadHash 与审批前冻结建议不一致")
    if frozen.get("idempotency_key") != order_data.get("idempotencyKey"):
        errors.append("当前 idempotencyKey 与审批前冻结建议不一致")
    return errors


def validate_action_retry(store: Any, user_id: str, order_data: dict[str, Any]) -> list[str]:
    if store is None:
        return []
    idem = str(order_data.get("idempotencyKey") or "")
    existing = load_procurement_action(store, user_id, idem)
    if not existing:
        return []
    if existing.get("payload_hash") != order_data.get("payloadHash"):
        return ["相同 idempotencyKey 已绑定不同 payloadHash，拒绝派发"]
    status = existing.get("status")
    if status in ("SENDING", "UNKNOWN"):
        return [f"采购动作状态为 {status}，须先调用 order_get_by_idempotency 回查，禁止重试建单"]
    if status == "CONFIRMED":
        return ["采购动作已 CONFIRMED，请读取已有订单，禁止再次派发"]
    return []


def record_procurement_result(
    store: Any,
    user_id: str,
    order_data: dict[str, Any],
    tool_result: Any,
) -> None:
    if store is None:
        return
    content = getattr(tool_result, "content", tool_result)
    parsed: Any = content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            parsed = {"message": content}
    code = parsed.get("code") if isinstance(parsed, dict) else None
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if code in (200, "200") or (code is None and isinstance(parsed, dict) and parsed.get("success") is True):
        status = "CONFIRMED"
    elif code in (202, "202") or (isinstance(data, dict) and data.get("operationStatus") == "UNKNOWN"):
        status = "UNKNOWN"
    else:
        status = "REJECTED"
    record = {
        "idempotency_key": order_data.get("idempotencyKey"),
        "suggestion_id": order_data.get("suggestion_id"),
        "calc_run_id": order_data.get("calc_run_id"),
        "payload_hash": order_data.get("payloadHash"),
        "status": status,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "result": parsed,
    }
    store.put(
        _namespace(ACTION_NAMESPACE, user_id),
        str(order_data.get("idempotencyKey")),
        record,
    )
