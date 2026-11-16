"""Static contract checks for Java ERP capabilities exposed through MCP.

These checks intentionally avoid importing FastMCP or starting Java/MySQL so contract
drift is caught even in the lightweight Python unit-test job.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def test_m1_to_m4_tools_are_registered_and_visible_to_agents() -> None:
    server = _read("src/mcp_server/server_main.py")
    catalog = _read("src/mcp_server/tools/catalog_tools.py")
    workflow = _read("src/mcp_server/tools/procurement_flow_tools.py")
    analyst = _read("src/agent/subagents/configs/procurement_analyst.yaml")
    order_agent = _read("src/agent/subagents/configs/procurement_order.yaml")

    assert "register_catalog_tools(mcp)" in server
    assert "register_procurement_flow_tools(mcp)" in server

    expected_read_tools = {
        "supplier_options",
        "vehicle_model_search",
        "vehicle_model_get",
        "part_fitments",
        "part_search_by_vehicle",
        "inventory_transaction_page",
        "inventory_transaction_get",
        "replenishment_page",
        "purchase_return_page",
    }
    expected_write_tools = {
        "order_receive",
        "replenishment_create",
        "replenishment_inspect",
        "replenishment_create_order",
        "replenishment_complete",
        "replenishment_cancel",
        "purchase_return_create",
        "purchase_return_confirm",
    }
    defined = set(re.findall(r"async def ([a-z0-9_]+)\(", catalog + workflow))
    assert expected_read_tools | expected_write_tools <= defined
    assert all(f"  - {name}\n" in analyst for name in expected_read_tools)
    assert all(f"  - {name}\n" in order_agent for name in expected_write_tools)


def test_order_status_contract_is_one_through_five_everywhere() -> None:
    order_tools = _read("src/mcp_server/tools/order_tools.py")
    order_agent = _read("src/agent/subagents/configs/procurement_order.yaml")
    mock = _read("deploy/mock-erp/erp_mock_server.py")

    for value, label in enumerate(("待审核", "已审核", "采购中", "已入库", "已取消"), 1):
        assert f"{value}={label}" in order_tools
        assert label in order_agent
        assert f'{value}: "{label}"' in mock

    assert "status not in (0, 1, 2, 3, 4)" not in mock
    assert 'payload.get("status", 0)' not in mock
    assert 'for field in ("orderNumber", "status", "remark")' not in mock


def test_legacy_java_technical_packages_are_frozen() -> None:
    """New modules must be feature packages; this allowlist may only shrink."""
    java_root = REPO / "java_erp/src/main/java/com/motorparts"
    allowed = {
        "controller": {
            "AuthController", "BusinessAuditController", "InventoryController",
            "JwkController", "LogisticsController", "OperationController",
            "PartController", "PurchaseOrderController", "SecurityAdminController",
            "StatisticsController", "SupplierController",
        },
        "service": {
            "ErpOperationService", "InventoryService", "LogisticsService",
            "PartService", "PurchaseOrderService", "SupplierService",
        },
        "service/impl": {
            "ErpOperationServiceImpl", "InventoryServiceImpl", "LogisticsServiceImpl",
            "PartServiceImpl", "PurchaseOrderServiceImpl", "SupplierServiceImpl",
        },
        "entity": {
            "BaseEntity", "ErpOperation", "Inventory", "Logistics", "OrderDetail",
            "OrderDetailWithPart", "OrderIdempotency", "Part", "PurchaseOrder",
            "PurchaseOrderWithDetails", "Supplier", "User",
        },
        "mapper": {
            "ErpOperationMapper", "InventoryMapper", "LogisticsMapper",
            "OrderDetailMapper", "OrderIdempotencyMapper", "PartMapper",
            "PurchaseOrderMapper", "SupplierMapper", "UserMapper",
        },
    }
    for relative, grandfathered in allowed.items():
        actual = {path.stem for path in (java_root / relative).glob("*.java")}
        assert actual <= grandfathered, (
            f"new class in frozen technical package {relative}: "
            f"{sorted(actual - grandfathered)}"
        )
