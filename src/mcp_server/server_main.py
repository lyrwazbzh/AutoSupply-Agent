"""
MCP Server 入口
FastMCP 实例创建，注册所有 tools，SSE 传输协议
"""
import os
import sys

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastmcp import FastMCP
import uvicorn

from src.agent.log_utils import mcp_logger
from src.mcp_server.auth import ERPJwtVerifier
from src.mcp_server.server_config import MCP_HOST, MCP_PORT
from src.mcp_server.tools.catalog_tools import register_catalog_tools
from src.mcp_server.tools.inventory_tools import register_inventory_tools
from src.mcp_server.tools.order_tools import register_order_tools
from src.mcp_server.tools.parts_tools import register_parts_tools
from src.mcp_server.tools.procurement_flow_tools import register_procurement_flow_tools
from src.mcp_server.tools.suppliers_tools import register_supplier_tools
from src.observability import instrument_asgi

# 创建 MCP Server 实例
mcp = FastMCP(
    name="ERP-Procurement-MCP",
    instructions="摩托车零部件采购 MCP 网关：目录适配、供应商报价、采购、收货、库存、补货与退货。",
    auth=ERPJwtVerifier() if os.getenv("MCP_AUTH_ENABLED", "false").lower() in {"1", "true", "yes"} else None,
)

# 注册所有工具
register_supplier_tools(mcp)
register_parts_tools(mcp)
register_order_tools(mcp)
register_inventory_tools(mcp)
register_catalog_tools(mcp)
register_procurement_flow_tools(mcp)


if __name__ == "__main__":
    mcp_logger.info(
        "Starting MCP Server on %s:%s (SSE transport)", MCP_HOST, MCP_PORT
    )
    app = instrument_asgi(mcp.http_app(transport="sse"), "erp-agent-mcp")
    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT, log_config=None)
