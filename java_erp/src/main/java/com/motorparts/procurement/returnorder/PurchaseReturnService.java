package com.motorparts.procurement.returnorder;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.Result;
import com.motorparts.common.enums.OrderStatusEnum;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.entity.Inventory;
import com.motorparts.entity.OrderDetail;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.inventory.transaction.InventoryCommandService;
import com.motorparts.inventory.transaction.InventoryTransactionMapper;
import com.motorparts.inventory.transaction.InventoryTransactionType;
import com.motorparts.mapper.InventoryMapper;
import com.motorparts.mapper.OrderDetailMapper;
import com.motorparts.mapper.PurchaseOrderMapper;
import com.motorparts.service.ErpOperationService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class PurchaseReturnService {
    private final PurchaseReturnMapper returnMapper;
    private final PurchaseOrderMapper orderMapper;
    private final OrderDetailMapper detailMapper;
    private final InventoryMapper inventoryMapper;
    private final InventoryTransactionMapper transactionMapper;
    private final ErpOperationService operationService;

    public Page<PurchaseReturn> page(long current, long size, String status, Long orderId, Long partId,
                                     String reasonType, LocalDateTime startTime, LocalDateTime endTime) {
        LambdaQueryWrapper<PurchaseReturn> query = new LambdaQueryWrapper<>();
        query.eq(StringUtils.hasText(status), PurchaseReturn::getStatus, normalize(status))
                .eq(orderId != null, PurchaseReturn::getPurchaseOrderId, orderId)
                .eq(partId != null, PurchaseReturn::getPartId, partId)
                .eq(StringUtils.hasText(reasonType), PurchaseReturn::getReasonType, normalize(reasonType))
                .ge(startTime != null, PurchaseReturn::getCreateTime, startTime)
                .le(endTime != null, PurchaseReturn::getCreateTime, endTime)
                .orderByDesc(PurchaseReturn::getCreateTime)
                .orderByDesc(PurchaseReturn::getId);
        return returnMapper.selectPage(new Page<>(current, size), query);
    }

    @Transactional(rollbackFor = Exception.class)
    public Result<?> create(PurchaseReturnRequests.Create request, String operationId, Long operatorId) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) return replay;
        if (request == null || request.purchaseOrderId() == null || request.partId() == null
                || request.quantity() == null || request.quantity() <= 0) {
            return Result.paramError("purchaseOrderId、partId 不能为空且 quantity 必须大于 0");
        }
        PurchaseReturnReasonType reasonType = PurchaseReturnReasonType.parse(request.reasonType());
        if (reasonType == null) {
            return Result.paramError("reasonType 必须为 QUANTITY_MISMATCH、DAMAGED、SPEC_MISMATCH、QUALITY_ISSUE 或 OTHER");
        }
        if (reasonType == PurchaseReturnReasonType.OTHER && !StringUtils.hasText(request.reason())) {
            return Result.paramError("reasonType 为 OTHER 时 reason 不能为空");
        }
        String normalizedOperationId = normalizeOperationId(operationId);
        if (normalizedOperationId != null && normalizedOperationId.length() > 128) {
            return Result.paramError("operationId 长度不能超过 128");
        }

        PurchaseOrder order = orderMapper.selectByIdForUpdate(request.purchaseOrderId());
        Result<?> validation = validateStoredOrder(order);
        if (validation != null) return validation;
        int orderedQuantity = orderedQuantity(detailMapper.selectByOrderIdForUpdate(order.getId()), request.partId());
        if (orderedQuantity <= 0) {
            return Result.error(ResultCode.BUSINESS_ERROR, "该采购单不包含指定零件");
        }
        int confirmedQuantity = returnMapper.sumConfirmedQuantity(order.getId(), request.partId());
        if ((long) confirmedQuantity + request.quantity() > orderedQuantity) {
            return Result.error(ResultCode.BUSINESS_ERROR, "退货数量超过该采购单可退数量");
        }

        LocalDateTime now = LocalDateTime.now();
        PurchaseReturn purchaseReturn = new PurchaseReturn();
        purchaseReturn.setReturnNumber(returnNumber(now));
        purchaseReturn.setPurchaseOrderId(order.getId());
        purchaseReturn.setPartId(request.partId());
        purchaseReturn.setQuantity(request.quantity());
        purchaseReturn.setReasonType(reasonType.name());
        purchaseReturn.setReason(trimToNull(request.reason()));
        purchaseReturn.setStatus(PurchaseReturnStatus.PENDING.name());
        purchaseReturn.setOperationId(normalizedOperationId);
        purchaseReturn.setCreatedBy(operatorId);
        purchaseReturn.setCreateTime(now);
        purchaseReturn.setUpdateTime(now);
        returnMapper.insert(purchaseReturn);

        Result<?> result = Result.success(purchaseReturn, "采购退货单创建成功");
        operationService.complete(normalizedOperationId, result);
        return result;
    }

    @Transactional(rollbackFor = Exception.class)
    public Result<?> confirm(Long returnId, String operationId, Long operatorId) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) return replay;
        if (returnId == null) return Result.paramError("退货单ID不能为空");
        String normalizedOperationId = normalizeOperationId(operationId);
        if (normalizedOperationId != null && normalizedOperationId.length() > 128) {
            return Result.paramError("operationId 长度不能超过 128");
        }

        PurchaseReturn purchaseReturn = returnMapper.selectByIdForUpdate(returnId);
        if (purchaseReturn == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS, "采购退货单不存在");
        }
        if (!PurchaseReturnStatus.PENDING.name().equals(purchaseReturn.getStatus())) {
            return Result.error(ResultCode.BUSINESS_ERROR, "只有待确认的采购退货单可以确认");
        }

        PurchaseOrder order = orderMapper.selectByIdForUpdate(purchaseReturn.getPurchaseOrderId());
        Result<?> validation = validateStoredOrder(order);
        if (validation != null) return validation;
        int orderedQuantity = orderedQuantity(detailMapper.selectByOrderIdForUpdate(order.getId()),
                purchaseReturn.getPartId());
        int confirmedQuantity = returnMapper.sumConfirmedQuantity(order.getId(), purchaseReturn.getPartId());
        if (orderedQuantity <= 0 || (long) confirmedQuantity + purchaseReturn.getQuantity() > orderedQuantity) {
            return Result.error(ResultCode.BUSINESS_ERROR, "累计确认退货数量超过原采购数量");
        }

        Inventory inventory = inventoryMapper.selectByPartIdForUpdate(purchaseReturn.getPartId());
        if (inventory == null || inventory.getCurrentQuantity() == null
                || inventory.getCurrentQuantity() < purchaseReturn.getQuantity()) {
            return Result.error(ResultCode.INSUFFICIENT_INVENTORY, "当前库存不足，无法确认采购退货");
        }
        int before = inventory.getCurrentQuantity();
        int after = before - purchaseReturn.getQuantity();
        LocalDateTime confirmedAt = LocalDateTime.now();
        if (inventoryMapper.applyOutbound(inventory.getId(), purchaseReturn.getQuantity(), after, confirmedAt) != 1) {
            return Result.error(ResultCode.INSUFFICIENT_INVENTORY, "当前库存不足，无法确认采购退货");
        }
        transactionMapper.insert(InventoryCommandService.transaction(
                purchaseReturn.getPartId(), InventoryTransactionType.PURCHASE_RETURN,
                purchaseReturn.getQuantity(), before, after, "PURCHASE_RETURN", purchaseReturn.getId(),
                normalizedOperationId, operatorId, inventory.getWarehouseLocation(),
                purchaseReturn.getReason(), confirmedAt));
        if (returnMapper.markConfirmed(purchaseReturn.getId(), normalizedOperationId, operatorId, confirmedAt) != 1) {
            throw new IllegalStateException("采购退货单状态已变化，确认退货失败: returnId=" + returnId);
        }

        PurchaseReturn confirmed = returnMapper.selectById(returnId);
        Result<?> result = Result.success(confirmed, "采购退货确认成功，库存已扣减");
        operationService.complete(normalizedOperationId, result);
        return result;
    }

    private static Result<?> validateStoredOrder(PurchaseOrder order) {
        if (order == null) return Result.error(ResultCode.DATA_NOT_EXISTS, "来源采购单不存在");
        if (!OrderStatusEnum.STORED.getCode().equals(order.getStatus())) {
            return Result.error(ResultCode.ORDER_STATUS_ERROR, "只有已入库的采购订单可以发起退货");
        }
        return null;
    }

    private static int orderedQuantity(List<OrderDetail> details, Long partId) {
        if (details == null || partId == null) return 0;
        int quantity = 0;
        for (OrderDetail detail : details) {
            if (partId.equals(detail.getPartId()) && detail.getQuantity() != null && detail.getQuantity() > 0) {
                quantity = Math.addExact(quantity, detail.getQuantity());
            }
        }
        return quantity;
    }

    private static String returnNumber(LocalDateTime now) {
        return "PR-" + now.format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss")) + "-"
                + UUID.randomUUID().toString().replace("-", "").substring(0, 8).toUpperCase();
    }

    private static String normalize(String value) {
        return value == null ? null : value.trim().toUpperCase();
    }

    private static String normalizeOperationId(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private static String trimToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }
}
