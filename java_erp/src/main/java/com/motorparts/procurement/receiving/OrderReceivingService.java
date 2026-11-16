package com.motorparts.procurement.receiving;

import com.motorparts.common.Result;
import com.motorparts.common.enums.OrderStatusEnum;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.entity.Inventory;
import com.motorparts.entity.OrderDetail;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.entity.PurchaseOrderWithDetails;
import com.motorparts.inventory.transaction.InventoryCommandService;
import com.motorparts.inventory.transaction.InventoryTransactionMapper;
import com.motorparts.inventory.transaction.InventoryTransactionType;
import com.motorparts.mapper.InventoryMapper;
import com.motorparts.mapper.OrderDetailMapper;
import com.motorparts.mapper.PartMapper;
import com.motorparts.mapper.PurchaseOrderMapper;
import com.motorparts.replenishment.ReplenishmentTaskMapper;
import com.motorparts.service.ErpOperationService;
import com.motorparts.service.PurchaseOrderService;
import com.motorparts.supplier.quotation.SupplierPartMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

@Service
@RequiredArgsConstructor
public class OrderReceivingService {
    private static final String DEFAULT_LOCATION = "A区-1号库";

    private final PurchaseOrderMapper orderMapper;
    private final OrderDetailMapper detailMapper;
    private final PartMapper partMapper;
    private final InventoryMapper inventoryMapper;
    private final InventoryTransactionMapper transactionMapper;
    private final SupplierPartMapper supplierPartMapper;
    private final ReplenishmentTaskMapper replenishmentTaskMapper;
    private final PurchaseOrderService orderService;
    private final ErpOperationService operationService;

    @Transactional(rollbackFor = Exception.class)
    public Result<?> receive(Long orderId, OrderReceiveRequest request, String operationId, Long operatorId) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) {
            return replay;
        }
        PurchaseOrder order = orderMapper.selectByIdForUpdate(orderId);
        if (order == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        if (!OrderStatusEnum.PURCHASING.getCode().equals(order.getStatus())) {
            return Result.error(ResultCode.ORDER_STATUS_ERROR, "只有采购中的订单可以确认收货");
        }

        List<OrderDetail> details = detailMapper.selectByOrderIdForUpdate(orderId);
        if (details == null || details.isEmpty()) {
            return Result.error(ResultCode.BUSINESS_ERROR, "采购订单没有可收货明细");
        }
        Map<Long, Integer> quantities = new TreeMap<>();
        for (OrderDetail detail : details) {
            if (detail.getPartId() == null || detail.getQuantity() == null || detail.getQuantity() <= 0) {
                return Result.error(ResultCode.BUSINESS_ERROR, "采购订单包含无效明细");
            }
            quantities.merge(detail.getPartId(), detail.getQuantity(), Math::addExact);
        }

        LocalDate actualArrivalDate = request != null && request.getActualArrivalDate() != null
                ? request.getActualArrivalDate() : LocalDate.now();
        String requestedLocation = request == null ? null : request.getWarehouseLocation();
        String remark = request == null ? null : request.getRemark();
        LocalDateTime occurredAt = LocalDateTime.now();
        List<OrderReceiveResponse.ReceivedLine> received = new ArrayList<>();

        for (Map.Entry<Long, Integer> entry : quantities.entrySet()) {
            Long partId = entry.getKey();
            int quantity = entry.getValue();
            if (partMapper.selectById(partId) == null) {
                throw new IllegalStateException("采购订单引用的零部件不存在: partId=" + partId);
            }
            String initialLocation = StringUtils.hasText(requestedLocation)
                    ? requestedLocation.trim() : DEFAULT_LOCATION;
            inventoryMapper.insertEmptyIfAbsent(partId, initialLocation);
            Inventory inventory = inventoryMapper.selectByPartIdForUpdate(partId);
            if (inventory == null) {
                throw new IllegalStateException("收货时无法创建库存记录: partId=" + partId);
            }
            int before = inventory.getCurrentQuantity();
            int after = Math.addExact(before, quantity);
            if (inventoryMapper.applyInbound(inventory.getId(), after, requestedLocation, occurredAt) != 1) {
                throw new IllegalStateException("采购收货库存更新失败: partId=" + partId);
            }
            String effectiveLocation = StringUtils.hasText(requestedLocation)
                    ? requestedLocation.trim() : inventory.getWarehouseLocation();
            transactionMapper.insert(InventoryCommandService.transaction(partId,
                    InventoryTransactionType.PURCHASE_RECEIPT, quantity, before, after,
                    "PURCHASE_ORDER", orderId, operationId, operatorId, effectiveLocation, remark, occurredAt));
            if (order.getSupplierId() != null) {
                supplierPartMapper.touchSupplierPurchase(partId, order.getSupplierId(), occurredAt);
            } else {
                supplierPartMapper.touchDefaultSupplierPurchase(partId, occurredAt);
            }
            received.add(new OrderReceiveResponse.ReceivedLine(partId, quantity, before, after, effectiveLocation));
        }

        if (orderMapper.markReceived(orderId, actualArrivalDate) != 1) {
            throw new IllegalStateException("采购订单状态已变化，确认收货失败: orderId=" + orderId);
        }
        replenishmentTaskMapper.completeByRelatedOrderId(orderId, occurredAt);
        PurchaseOrderWithDetails receivedOrder = orderService.loadOrderWithDetails(orderId);
        OrderReceiveResponse response = new OrderReceiveResponse(orderId, order.getOrderNumber(),
                OrderStatusEnum.STORED.getCode(), actualArrivalDate, operationId, List.copyOf(received), receivedOrder);
        Result<?> result = Result.success(response, "确认收货并入库成功");
        operationService.complete(operationId, result);
        return result;
    }
}
