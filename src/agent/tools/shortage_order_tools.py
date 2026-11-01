"""缺料 M2 工具：固化建议供 HITL 建单。"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from ..runtime_context import get_current_store, get_current_user_id
from ..shortage import suggestion as suggestion_mod
from ..shortage.actions import persist_frozen_suggestion


@tool
def freeze_shortage_suggestion(calc_result_json: str, remark: str = "") -> str:
    """将 shortage_calc 的 CalcResult 固化为不可改审批/建单 payload。

    固化后须用返回的 order_payload 原样调用 order_create（触发 HITL）；
    禁止手改 quantity/unitPrice。同一 calc_run_id 的 idempotencyKey 保证幂等建单。

    Args:
        calc_result_json: shortage_calc 返回的 data 对象 JSON，或完整 {code,data} 信封
        remark: 可选订单备注

    Returns:
        含 suggestion_id / idempotency_key / order_payload 的 JSON
    """
    try:
        raw = json.loads(calc_result_json) if isinstance(calc_result_json, str) else calc_result_json
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"JSON解析失败: {e}"}, ensure_ascii=False)

    calc = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
    try:
        frozen = suggestion_mod.freeze_shortage_suggestion(calc, remark=remark or "")
        persist_frozen_suggestion(
            get_current_store(), get_current_user_id(), frozen
        )
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    return json.dumps({"ok": True, "data": frozen}, ensure_ascii=False, indent=2)
