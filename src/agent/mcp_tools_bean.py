"""
MCP 工具分类 Bean
将 MCP 工具按制造供应链用途分组。
"""
from typing import List
from langchain_core.tools import BaseTool


# 分析子Agent使用的工具名关键字
ANALYST_TOOL_PATTERNS = [
    "supplier_query",
    "supplier_page",
    "supplier_get",
    "part_search",
    "part_page",
    "part_query",
    "part_by_supplier",
    "inventory_warning",
    "inventory_page",
    "inventory_check",
    "inventory_get",
    "order_search_details",
    "order_statistics",
    "order_page",
    "order_get",
    "generate_chart",
    "web_search",
    "program_search",
    "bom_get",
    "bom_compare",
    "material_get",
    "material_demand_get",
    "mrp_shortage_page",
    "kit_rate_get",
    "line_stop_risk_page",
]

# 订单子Agent使用的工具名关键字
ORDER_TOOL_PATTERNS = [
    "order_create",
    "order_update",
    "order_get",
    "order_page",
    "order_update_status",
    "request_order_info",
    "part_query",
    "part_search",
    "supplier_query",
    "supplier_get",
    "delivery_schedule_page",
    "delivery_performance_get",
    "supplier_quality_get",
]


def classify_tools(all_tools: List[BaseTool]) -> dict:
    """将工具按用途分类"""
    tool_map = {t.name: t for t in all_tools}

    analyst_tools = []
    order_tools = []

    for pattern in ANALYST_TOOL_PATTERNS:
        for name, tool in tool_map.items():
            if pattern in name and tool not in analyst_tools:
                analyst_tools.append(tool)

    for pattern in ORDER_TOOL_PATTERNS:
        for name, tool in tool_map.items():
            if pattern in name and tool not in order_tools:
                order_tools.append(tool)

    return {
        "analyst_tools": analyst_tools,
        "order_tools": order_tools,
        "planning_tools": [tool_map[name] for name in (
            "program_search", "bom_get", "bom_compare", "material_demand_get",
            "mrp_shortage_page", "kit_rate_get", "line_stop_risk_page",
        ) if name in tool_map],
        "sourcing_tools": [tool_map[name] for name in (
            "material_search", "material_get", "material_avl", "quotation_compare",
            "rfq_create", "sourcing_nominate", "ppap_status_get",
        ) if name in tool_map],
        "all_tools": all_tools,
    }
