"""由服务端填充已核验数值，LLM 只需解释原因与影响。"""

from __future__ import annotations

from typing import Any


def build_verified_facts(calc: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = str(calc.get("calc_run_id") or "")
    facts: list[dict[str, Any]] = []
    for line in calc.get("lines") or []:
        for metric in ("net_gap", "suggested_qty"):
            facts.append(
                {
                    "calc_run_id": run_id,
                    "part_id": line.get("part_id"),
                    "part_code": line.get("part_code"),
                    "part_name": line.get("part_name"),
                    "metric": metric,
                    "value": line.get(metric),
                    "unit": line.get("unit") or "",
                }
            )
    if calc.get("kit_rate") is not None:
        facts.append(
            {
                "calc_run_id": run_id,
                "part_id": None,
                "metric": "kit_rate",
                "value": calc.get("kit_rate"),
                "unit": "ratio",
                "scope": {
                    "vehicle_model": calc.get("vehicle_model"),
                    "plant_id": calc.get("plant_id"),
                    "as_of": calc.get("as_of"),
                    "horizon_days": calc.get("horizon_days"),
                    "definition": calc.get("material_kit_rate_definition"),
                },
            },
        )
    return facts


def render_verified_summary(calc: dict[str, Any]) -> str:
    """只从结构化结果拼装数字，不让模型重新生成采购数量。"""

    rows = [
        f"calc_run_id={calc.get('calc_run_id')}；物料种类齐套率={calc.get('kit_rate')}。"
    ]
    for line in calc.get("lines") or []:
        if float(line.get("net_gap") or 0) <= 0:
            continue
        rows.append(
            f"{line.get('part_name') or line.get('part_code') or line.get('part_id')}"
            f"（{line.get('part_code') or line.get('part_id')}）净缺口 {line.get('net_gap')}"
            f" {line.get('unit') or ''}，建议采购量 {line.get('suggested_qty')}"
            f" {line.get('unit') or ''}，首次缺料日 {line.get('first_shortage_date')}，"
            f"风险 {line.get('shortage_risk')}。"
        )
    return "\n".join(rows)
