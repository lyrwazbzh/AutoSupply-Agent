"""新能源汽车整车制造采购与供应链协同 MCP 工具。

本模块只负责将 Agent 的领域动作映射到 ERP/PLM/MES REST 契约；不在网关内
生成或猜测 BOM、MRP、质量和交付数据。部署前由后端实现相应 `/api/*` 接口。
"""
import json

from fastmcp import FastMCP

from ..http_base import erp_client


def _result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def register_manufacturing_tools(mcp: FastMCP) -> None:
    """注册制造供应链领域工具。"""

    @mcp.tool()
    async def program_search(keyword: str = None, status: str = None) -> str:
        """查询车型项目/平台。status 可为开发中、SOP、量产、停产。"""
        return _result(await erp_client.get("/api/programs/search", params={"keyword": keyword, "status": status}))

    @mcp.tool()
    async def bom_get(program_code: str, bom_version: str = None) -> str:
        """获取车型项目指定版本的制造 BOM。"""
        return _result(await erp_client.get(f"/api/boms/{program_code}", params={"bomVersion": bom_version}))

    @mcp.tool()
    async def bom_compare(program_code: str, from_version: str, to_version: str) -> str:
        """比较同一项目两个 BOM 版本的物料增删改。"""
        return _result(await erp_client.get("/api/boms/compare", params={"programCode": program_code, "fromVersion": from_version, "toVersion": to_version}))

    @mcp.tool()
    async def engineering_change_get(change_no: str) -> str:
        """获取工程变更单及其受影响的 BOM、物料、工厂和生效日期。"""
        return _result(await erp_client.get(f"/api/engineering-changes/{change_no}"))

    @mcp.tool()
    async def material_search(keyword: str = None, material_code: str = None, category: str = None) -> str:
        """按名称、物料编码或分类查询制造物料。"""
        return _result(await erp_client.get("/api/materials/search", params={"keyword": keyword, "materialCode": material_code, "category": category}))

    @mcp.tool()
    async def material_get(material_code: str) -> str:
        """获取物料主数据，包含图号、版本、关键件等级和单位。"""
        return _result(await erp_client.get(f"/api/materials/{material_code}"))

    @mcp.tool()
    async def material_alternatives(material_code: str) -> str:
        """查询已批准的替代料；替代料使用仍需遵守工程与质量放行。"""
        return _result(await erp_client.get(f"/api/materials/{material_code}/alternatives"))

    @mcp.tool()
    async def material_avl(material_code: str) -> str:
        """查询物料的 AVL（认可供应商名单）及定点状态。"""
        return _result(await erp_client.get(f"/api/materials/{material_code}/approved-suppliers"))

    @mcp.tool()
    async def mrp_shortage_page(
        current: int = 1, size: int = 20, plant_code: str = None,
        program_code: str = None, risk_level: str = None,
    ) -> str:
        """分页查询 MRP 缺料和潜在停线风险。"""
        return _result(await erp_client.get("/api/mrp/shortages", params={
            "current": current, "size": size, "plantCode": plant_code,
            "programCode": program_code, "riskLevel": risk_level,
        }))

    @mcp.tool()
    async def material_demand_get(material_code: str, plant_code: str, required_date: str = None) -> str:
        """获取物料净需求，含毛需求、现存、在途和未结订单。"""
        return _result(await erp_client.get("/api/mrp/material-demand", params={
            "materialCode": material_code, "plantCode": plant_code, "requiredDate": required_date,
        }))

    @mcp.tool()
    async def kit_rate_get(program_code: str, plant_code: str, production_date: str = None) -> str:
        """获取项目在指定工厂和日期的生产齐套率。"""
        return _result(await erp_client.get("/api/production/kit-rate", params={
            "programCode": program_code, "plantCode": plant_code, "productionDate": production_date,
        }))

    @mcp.tool()
    async def quotation_compare(rfq_no: str) -> str:
        """比较同一 RFQ 下供应商的价格、交期、产能和质量指标。"""
        return _result(await erp_client.get(f"/api/rfqs/{rfq_no}/quotation-comparison"))

    @mcp.tool()
    async def rfq_create(rfq_data: str) -> str:
        """创建 RFQ。数据须包含项目、物料、版本、数量、需求日期和候选供应商。"""
        try:
            payload = json.loads(rfq_data)
        except json.JSONDecodeError as exc:
            return _result({"code": 400, "message": f"RFQ JSON解析失败: {exc}", "data": None})
        return _result(await erp_client.post("/api/rfqs", json_data=payload))

    @mcp.tool()
    async def sourcing_nominate(nomination_data: str) -> str:
        """提交供应商定点申请；应附报价、AVL、PPAP、产能和风险评估依据。"""
        try:
            payload = json.loads(nomination_data)
        except json.JSONDecodeError as exc:
            return _result({"code": 400, "message": f"定点申请JSON解析失败: {exc}", "data": None})
        return _result(await erp_client.post("/api/sourcing-nominations", json_data=payload))

    @mcp.tool()
    async def delivery_schedule_page(
        current: int = 1, size: int = 20, supplier_code: str = None,
        plant_code: str = None, status: str = None,
    ) -> str:
        """查询供应商交付计划及其状态。"""
        return _result(await erp_client.get("/api/delivery-schedules", params={
            "current": current, "size": size, "supplierCode": supplier_code,
            "plantCode": plant_code, "status": status,
        }))

    @mcp.tool()
    async def asn_page(current: int = 1, size: int = 20, supplier_code: str = None, plant_code: str = None) -> str:
        """查询 ASN、预计到货时间、已发运数量和收货状态。"""
        return _result(await erp_client.get("/api/asns", params={
            "current": current, "size": size, "supplierCode": supplier_code, "plantCode": plant_code,
        }))

    @mcp.tool()
    async def delivery_performance_get(supplier_code: str, start_date: str = None, end_date: str = None) -> str:
        """查询供应商交付达成率、延期和欠交表现。"""
        return _result(await erp_client.get(f"/api/suppliers/{supplier_code}/delivery-performance", params={"startDate": start_date, "endDate": end_date}))

    @mcp.tool()
    async def supplier_quality_get(supplier_code: str) -> str:
        """查询供应商 PPM、来料不良、质量审核与整改状态。"""
        return _result(await erp_client.get(f"/api/suppliers/{supplier_code}/quality"))

    @mcp.tool()
    async def ppap_status_get(material_code: str, supplier_code: str) -> str:
        """查询供应商针对物料的 PPAP 放行状态。"""
        return _result(await erp_client.get("/api/quality/ppap-status", params={"materialCode": material_code, "supplierCode": supplier_code}))

    @mcp.tool()
    async def line_stop_risk_page(current: int = 1, size: int = 20, plant_code: str = None) -> str:
        """查询按工厂汇总的停线风险及建议处置。"""
        return _result(await erp_client.get("/api/risks/line-stop", params={"current": current, "size": size, "plantCode": plant_code}))

    @mcp.tool()
    async def supply_risk_assess(material_code: str, plant_code: str, supplier_code: str = None) -> str:
        """获得物料在指定工厂的综合供应风险，包括缺料、质量、交付、产能和单一来源。"""
        return _result(await erp_client.get("/api/risks/supply-assessment", params={
            "materialCode": material_code, "plantCode": plant_code, "supplierCode": supplier_code,
        }))
