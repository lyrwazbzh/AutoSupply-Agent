"""MCP tools for receiving, inventory ledger, replenishment and returns."""

import json

from fastmcp import FastMCP

from ..http_base import erp_client


def _write_headers(operation_id: str | None) -> dict | None:
    if not operation_id:
        return None
    return {"X-Operation-Id": operation_id, "Idempotency-Key": operation_id}


def _json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def register_procurement_flow_tools(mcp: FastMCP) -> None:
    """Register the Java ERP M2-M4 procurement workflow tools."""

    @mcp.tool()
    async def order_receive(
        id: int,
        actual_arrival_date: str = None,
        warehouse_location: str = None,
        remark: str = None,
        operation_id: str = None,
    ) -> str:
        """确认采购中的订单整单到货，并在同一事务中自动入库、生成库存流水。"""
        data = {
            "actualArrivalDate": actual_arrival_date,
            "warehouseLocation": warehouse_location,
            "remark": remark,
            "operationId": operation_id,
        }
        return _json(
            await erp_client.post(
                f"/api/orders/{id}/receive",
                json_data={key: value for key, value in data.items() if value is not None},
                params={"operationId": operation_id},
                headers=_write_headers(operation_id),
            )
        )

    @mcp.tool()
    async def inventory_transaction_page(
        current: int = 1,
        size: int = 20,
        part_id: int = None,
        transaction_type: str = None,
        source_type: str = None,
        source_id: int = None,
        operator_id: int = None,
        start_time: str = None,
        end_time: str = None,
        operation_id: str = None,
    ) -> str:
        """分页查询库存流水，可追踪库存变化来源、操作者和 operationId。"""
        return _json(
            await erp_client.get(
                "/api/inventory/transactions/page",
                params={
                    "current": current,
                    "size": size,
                    "partId": part_id,
                    "transactionType": transaction_type,
                    "sourceType": source_type,
                    "sourceId": source_id,
                    "operatorId": operator_id,
                    "startTime": start_time,
                    "endTime": end_time,
                    "operationId": operation_id,
                },
            )
        )

    @mcp.tool()
    async def inventory_transaction_get(id: int) -> str:
        """获取一条库存流水详情。"""
        return _json(await erp_client.get(f"/api/inventory/transactions/{id}"))

    @mcp.tool()
    async def replenishment_page(
        current: int = 1,
        size: int = 20,
        status: str = None,
        part_id: int = None,
        source: str = None,
    ) -> str:
        """分页查询补货任务。"""
        return _json(
            await erp_client.get(
                "/api/replenishment/page",
                params={
                    "current": current,
                    "size": size,
                    "status": status,
                    "partId": part_id,
                    "source": source,
                },
            )
        )

    @mcp.tool()
    async def replenishment_create(
        part_id: int,
        suggested_quantity: int = None,
        preferred_supplier_id: int = None,
        reason: str = None,
        operation_id: str = None,
    ) -> str:
        """人工创建补货任务。"""
        data = {
            "partId": part_id,
            "suggestedQuantity": suggested_quantity,
            "preferredSupplierId": preferred_supplier_id,
            "reason": reason,
            "operationId": operation_id,
        }
        return _json(
            await erp_client.post(
                "/api/replenishment/create",
                json_data={key: value for key, value in data.items() if value is not None},
                params={"operationId": operation_id},
                headers=_write_headers(operation_id),
            )
        )

    @mcp.tool()
    async def replenishment_inspect(operation_id: str = None) -> str:
        """立即执行一次确定性低库存巡检并生成缺失的补货任务。"""
        return _json(
            await erp_client.post(
                "/api/replenishment/inspect",
                params={"operationId": operation_id},
                headers=_write_headers(operation_id),
            )
        )

    @mcp.tool()
    async def replenishment_create_order(
        id: int,
        supplier_id: int = None,
        quantity: int = None,
        expected_delivery_date: str = None,
        remark: str = None,
        operation_id: str = None,
    ) -> str:
        """把待处理补货任务转换为采购订单。"""
        data = {
            "supplierId": supplier_id,
            "quantity": quantity,
            "expectedDeliveryDate": expected_delivery_date,
            "remark": remark,
            "operationId": operation_id,
        }
        return _json(
            await erp_client.post(
                f"/api/replenishment/{id}/create-order",
                json_data={key: value for key, value in data.items() if value is not None},
                params={"operationId": operation_id},
                headers=_write_headers(operation_id),
            )
        )

    @mcp.tool()
    async def replenishment_complete(id: int, operation_id: str = None) -> str:
        """完成一个补货任务。"""
        return _json(
            await erp_client.post(
                f"/api/replenishment/{id}/complete",
                params={"operationId": operation_id},
                headers=_write_headers(operation_id),
            )
        )

    @mcp.tool()
    async def replenishment_cancel(id: int, operation_id: str = None) -> str:
        """取消一个待处理补货任务。"""
        return _json(
            await erp_client.post(
                f"/api/replenishment/{id}/cancel",
                params={"operationId": operation_id},
                headers=_write_headers(operation_id),
            )
        )

    @mcp.tool()
    async def purchase_return_page(
        current: int = 1,
        size: int = 20,
        status: str = None,
        order_id: int = None,
        part_id: int = None,
        reason_type: str = None,
        start_time: str = None,
        end_time: str = None,
    ) -> str:
        """分页查询采购退货记录。"""
        return _json(
            await erp_client.get(
                "/api/purchase-returns/page",
                params={
                    "current": current,
                    "size": size,
                    "status": status,
                    "orderId": order_id,
                    "partId": part_id,
                    "reasonType": reason_type,
                    "startTime": start_time,
                    "endTime": end_time,
                },
            )
        )

    @mcp.tool()
    async def purchase_return_create(
        purchase_order_id: int,
        part_id: int,
        quantity: int,
        reason_type: str,
        reason: str = None,
        operation_id: str = None,
    ) -> str:
        """为已经入库的采购订单创建待确认退货单。"""
        data = {
            "purchaseOrderId": purchase_order_id,
            "partId": part_id,
            "quantity": quantity,
            "reasonType": reason_type,
            "reason": reason,
            "operationId": operation_id,
        }
        return _json(
            await erp_client.post(
                "/api/purchase-returns/create",
                json_data={key: value for key, value in data.items() if value is not None},
                params={"operationId": operation_id},
                headers=_write_headers(operation_id),
            )
        )

    @mcp.tool()
    async def purchase_return_confirm(id: int, operation_id: str = None) -> str:
        """确认采购退货并扣减对应库存、生成库存流水。"""
        return _json(
            await erp_client.post(
                f"/api/purchase-returns/{id}/confirm",
                params={"operationId": operation_id},
                headers=_write_headers(operation_id),
            )
        )
