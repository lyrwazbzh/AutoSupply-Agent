"""
缺料主链 MCP 工具
shortage_context / shortage_calc
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import FastMCP

from ..http_base import erp_client

# 保证可导入 agent.shortage（MCP 常以 src 为 cwd）
_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent.shortage.engine import run_shortage_calc  # noqa: E402
from agent.shortage.records import build_calc_record  # noqa: E402
from agent.shortage.report import build_verified_facts, render_verified_summary  # noqa: E402
from agent.shortage.schemas import (  # noqa: E402
    BomLine,
    CalcConfig,
    InventoryLine,
    OpenPoLine,
    PlanLine,
    SupplierConstraint,
)
from agent.shortage.validation import InputValidationError  # noqa: E402


def _context_to_calc_inputs(data: dict, safety_factor: float):
    bom = [
        BomLine(
            part_id=int(line["partId"]),
            qty_per_vehicle=float(line["qtyPerVehicle"]),
            part_code=line.get("partCode") or "",
            part_name=line.get("partName") or "",
            unit=line.get("unit") or "",
            purchase_price=float(line.get("purchasePrice") or 0),
            bom_version=data.get("bom", {}).get("bomVersion") or "",
            price_ref=line.get("priceRef") or f"part:{line['partId']}:purchasePrice",
        )
        for line in data["bom"]["lines"]
    ]
    plans = [
        PlanLine(
            plan_id=p["planId"],
            vehicle_model=p["vehicleModel"],
            plant_id=p["plantId"],
            plan_date=p["planDate"],
            quantity=int(p["quantity"]),
        )
        for p in data["plans"]
    ]
    inventory = [
        InventoryLine(
            part_id=int(row["partId"]),
            on_hand=int(row["onHand"]),
            allocated=int(row.get("allocated") or 0),
            inventory_id=row.get("inventoryId"),
            unit=row.get("unit") or "",
            status=row.get("inventoryStatus") or "available",
        )
        for row in data["inventory"]
    ]
    open_pos = [
        OpenPoLine(
            part_id=int(row["partId"]),
            quantity=int(row["quantity"]),
            expected_date=row["expectedDate"],
            order_number=row.get("orderNumber") or "",
            order_status=int(row.get("orderStatus") or 1),
            unit=row.get("unit") or "",
            received_qty=int(row.get("receivedQty") or 0),
        )
        for row in data["openPos"]
    ]
    suppliers = [
        SupplierConstraint(
            part_id=int(row["partId"]),
            supplier_id=int(row["supplierId"]),
            supplier_name=row.get("supplierName") or "",
            status=int(row.get("status") or 0),
            credit_rating=row.get("creditRating") or "",
            lead_time_days=int(row.get("leadTimeDays") or 0),
            moq=int(row.get("moq") or 1),
            order_multiple=int(row.get("orderMultiple") or 1),
            max_order_qty=(
                int(row["maxOrderQty"])
                if row.get("maxOrderQty") is not None
                else None
            ),
        )
        for row in data["suppliers"]
    ]
    config = CalcConfig(
        vehicle_model=data["vehicleModel"],
        plant_id=data["plantId"],
        as_of=data["asOf"],
        horizon_days=int(data["horizonDays"]),
        safety_factor=safety_factor,
    )
    return config, bom, plans, inventory, open_pos, suppliers


def register_shortage_tools(mcp: FastMCP):
    """注册缺料主链工具。"""

    @mcp.tool()
    async def shortage_context(
        vehicle_model: str,
        plant_id: str,
        horizon_days: int = 7,
        as_of: str = None,
    ) -> str:
        """获取缺料计算所需 ERP 快照（BOM、计划、库存、在途、供应商交期）。

        Args:
            vehicle_model: 车型编码，演示种子为 A-125
            plant_id: 工厂编码，演示种子为 PLANT-HZ
            horizon_days: 展望窗口天数，默认 7
            as_of: 数据时点 yyyy-MM-dd；为空则用服务当日

        Returns:
            缺料上下文 JSON，含 caliberVersion / bom / plans / inventory / openPos / suppliers
        """
        params = {
            "vehicleModel": vehicle_model,
            "plantId": plant_id,
            "horizonDays": horizon_days,
            "asOf": as_of,
        }
        result = await erp_client.get("/api/shortage/context", params=params)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def shortage_calc(
        vehicle_model: str,
        plant_id: str,
        horizon_days: int = 7,
        as_of: str = None,
        safety_factor: float = 0.1,
    ) -> str:
        """按 shortage-口径/v2 确定性计算按日缺口与补货建议（禁止心算）。

        先拉取 ERP 快照，再由 shortage_engine 计算；返回带 calc_run_id 的结果。

        Args:
            vehicle_model: 车型编码，演示种子为 A-125
            plant_id: 工厂编码，演示种子为 PLANT-HZ
            horizon_days: 展望窗口天数，默认 7
            as_of: 数据时点 yyyy-MM-dd
            safety_factor: 建议量安全系数，默认 0.1

        Returns:
            CalcResult JSON（缺口行、齐套率、金额汇总、证据引用）
        """
        params = {
            "vehicleModel": vehicle_model,
            "plantId": plant_id,
            "horizonDays": horizon_days,
            "asOf": as_of,
        }
        envelope = await erp_client.get("/api/shortage/context", params=params)
        if envelope.get("code") != 200 or not envelope.get("data"):
            return json.dumps(envelope, ensure_ascii=False, indent=2)

        data = envelope["data"]
        config, bom, plans, inventory, open_pos, suppliers = _context_to_calc_inputs(
            data, safety_factor
        )
        read_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        source_versions = dict(data.get("sourceVersions") or {})
        source_versions.setdefault("bom", data.get("bom", {}).get("bomVersion"))
        source_versions.setdefault("erp_caliber", data.get("caliberVersion"))
        try:
            result = run_shortage_calc(
                config=config,
                bom=bom,
                plans=plans,
                inventory=inventory,
                open_pos=open_pos,
                suppliers=suppliers,
                source_versions=source_versions,
                source_read_times=dict(data.get("sourceReadTimes") or {"erp": read_at}),
            )
        except InputValidationError as exc:
            return json.dumps(
                {
                    "code": 422,
                    "message": "缺料输入业务校验未通过",
                    "errors": [issue.to_dict() for issue in exc.issues],
                    "data": None,
                },
                ensure_ascii=False,
                indent=2,
            )
        payload = result.to_dict()
        payload["calc_record"] = build_calc_record(result).to_dict()
        payload["verified_facts"] = build_verified_facts(payload)
        payload["verified_summary"] = render_verified_summary(payload)
        payload["erpContext"] = {
            "bomVersion": data.get("bom", {}).get("bomVersion"),
            "windowEnd": data.get("windowEnd"),
            "planCount": len(data.get("plans") or []),
            "openPoCount": len(data.get("openPos") or []),
        }
        return json.dumps(
            {"code": 200, "message": "success", "data": payload},
            ensure_ascii=False,
            indent=2,
        )
