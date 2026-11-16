package com.motorparts.inventory.transaction;

import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.dto.InventoryWithPart;
import com.motorparts.entity.Inventory;
import com.motorparts.mapper.InventoryMapper;
import com.motorparts.mapper.PartMapper;
import com.motorparts.service.ErpOperationService;
import com.motorparts.service.InventoryService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class InventoryCommandService {
    private static final String DEFAULT_LOCATION = "A区-1号库";

    private final InventoryMapper inventoryMapper;
    private final InventoryTransactionMapper transactionMapper;
    private final PartMapper partMapper;
    private final InventoryService inventoryService;
    private final ErpOperationService operationService;

    @Transactional(rollbackFor = Exception.class)
    public Result<?> inbound(Long partId, Integer quantity, String warehouseLocation,
                             String operationId, Long operatorId, String remark) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) {
            return replay;
        }
        if (partId == null || quantity == null || quantity <= 0) {
            return Result.paramError("partId 不能为空且 quantity 必须大于 0");
        }
        if (partMapper.selectById(partId) == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS, "零部件不存在");
        }

        String location = StringUtils.hasText(warehouseLocation) ? warehouseLocation.trim() : DEFAULT_LOCATION;
        inventoryMapper.insertEmptyIfAbsent(partId, location);
        Inventory inventory = inventoryMapper.selectByPartIdForUpdate(partId);
        if (inventory == null) {
            throw new IllegalStateException("创建库存记录后无法读取: partId=" + partId);
        }

        int before = inventory.getCurrentQuantity();
        int after = Math.addExact(before, quantity);
        LocalDateTime occurredAt = LocalDateTime.now();
        if (inventoryMapper.applyInbound(inventory.getId(), after, warehouseLocation, occurredAt) != 1) {
            throw new IllegalStateException("库存入库更新失败: partId=" + partId);
        }
        String effectiveLocation = StringUtils.hasText(warehouseLocation)
                ? warehouseLocation.trim() : inventory.getWarehouseLocation();
        transactionMapper.insert(transaction(partId, InventoryTransactionType.MANUAL_INBOUND, quantity,
                before, after, "MANUAL", null, operationId, operatorId, effectiveLocation, remark, occurredAt));

        InventoryWithPart view = inventoryService.getInventoryWithPartByPartId(partId);
        Result<?> result = Result.success(view, "入库成功");
        operationService.complete(operationId, result);
        return result;
    }

    @Transactional(rollbackFor = Exception.class)
    public Result<?> outbound(Long partId, Integer quantity, String operationId, Long operatorId, String remark) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) {
            return replay;
        }
        if (partId == null || quantity == null || quantity <= 0) {
            return Result.paramError("partId 不能为空且 quantity 必须大于 0");
        }

        Inventory inventory = inventoryMapper.selectByPartIdForUpdate(partId);
        if (inventory == null || inventory.getCurrentQuantity() < quantity) {
            return Result.error(ResultCode.INSUFFICIENT_INVENTORY);
        }
        int before = inventory.getCurrentQuantity();
        int after = before - quantity;
        LocalDateTime occurredAt = LocalDateTime.now();
        if (inventoryMapper.applyOutbound(inventory.getId(), quantity, after, occurredAt) != 1) {
            return Result.error(ResultCode.INSUFFICIENT_INVENTORY);
        }
        transactionMapper.insert(transaction(partId, InventoryTransactionType.MANUAL_OUTBOUND, quantity,
                before, after, "MANUAL", null, operationId, operatorId,
                inventory.getWarehouseLocation(), remark, occurredAt));

        InventoryWithPart view = inventoryService.getInventoryWithPartByPartId(partId);
        Result<?> result = Result.success(view, "出库成功");
        operationService.complete(operationId, result);
        return result;
    }

    public static InventoryTransaction transaction(
            Long partId, InventoryTransactionType type, int quantity, int before, int after,
            String sourceType, Long sourceId, String operationId, Long operatorId,
            String warehouseLocation, String remark, LocalDateTime occurredAt) {
        InventoryTransaction row = new InventoryTransaction();
        row.setTransactionNo("ITX-" + UUID.randomUUID().toString().replace("-", ""));
        row.setPartId(partId);
        row.setTransactionType(type.name());
        row.setQuantity(quantity);
        row.setBeforeQuantity(before);
        row.setAfterQuantity(after);
        row.setSourceType(sourceType);
        row.setSourceId(sourceId);
        row.setOperationId(StringUtils.hasText(operationId) ? operationId.trim() : null);
        row.setOperatorId(operatorId);
        row.setWarehouseLocation(warehouseLocation);
        row.setRemark(remark);
        row.setOccurredAt(occurredAt);
        row.setCreateTime(occurredAt);
        return row;
    }
}
