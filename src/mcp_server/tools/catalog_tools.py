"""MCP tools for the motorcycle parts procurement catalog."""

import json

from fastmcp import FastMCP

from ..http_base import erp_client


def register_catalog_tools(mcp: FastMCP) -> None:
    """Register read-only supplier quotation and fitment tools."""

    @mcp.tool()
    async def supplier_options(part_id: int) -> str:
        """查询一个零件的全部供应商报价、交期、起订量和质量评分。"""
        result = await erp_client.get(f"/api/parts/{part_id}/supplier-options")
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def vehicle_model_search(
        keyword: str = None,
        brand: str = None,
        series: str = None,
        model: str = None,
        year: int = None,
        displacement: int = None,
        limit: int = 50,
    ) -> str:
        """搜索摩托车车型档案，可按品牌、系列、车型、年款和排量筛选。"""
        result = await erp_client.get(
            "/api/vehicle-models/search",
            params={
                "keyword": keyword,
                "brand": brand,
                "series": series,
                "model": model,
                "year": year,
                "displacement": displacement,
                "limit": limit,
            },
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def vehicle_model_get(id: int) -> str:
        """按 ID 获取摩托车车型详情。"""
        result = await erp_client.get(f"/api/vehicle-models/{id}")
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def part_fitments(part_id: int) -> str:
        """查询一个零件适配的全部摩托车车型。"""
        result = await erp_client.get(f"/api/parts/{part_id}/fitments")
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def part_search_by_vehicle(vehicle_model_id: int) -> str:
        """按车型 ID 查询全部适配零件。"""
        result = await erp_client.get(
            "/api/parts/search-by-vehicle",
            params={"vehicleModelId": vehicle_model_id},
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
