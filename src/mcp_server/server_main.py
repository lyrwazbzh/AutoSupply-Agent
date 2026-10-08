"""
MCP Server 入口
FastMCP 实例创建，注册所有 tools，SSE 传输协议
"""
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastmcp import FastMCP
from src.mcp_server.server_config import MCP_HOST, MCP_PORT
from src.mcp_server.tools.suppliers_tools import register_supplier_tools
from src.mcp_server.tools.parts_tools import register_parts_tools
from src.mcp_server.tools.order_tools import register_order_tools
from src.mcp_server.tools.inventory_tools import register_inventory_tools
from src.mcp_server.tools.manufacturing_tools import register_manufacturing_tools

# 创建 MCP Server 实例
mcp = FastMCP(
    name="AutoSupply-MCP",
    instructions=(
        "新能源汽车整车制造采购与供应链协同 MCP 网关，提供物料、项目/BOM、"
        "MRP、寻源定点、交付、质量、风险及存量 ERP 订单和库存能力。"
    ),
)

# 注册所有工具
register_supplier_tools(mcp)
register_parts_tools(mcp)
register_order_tools(mcp)
register_inventory_tools(mcp)
register_manufacturing_tools(mcp)


if __name__ == "__main__":
    print(f"🚀 Starting MCP Server on {MCP_HOST}:{MCP_PORT} (SSE transport)")
    mcp.run(transport="sse", host=MCP_HOST, port=MCP_PORT)
