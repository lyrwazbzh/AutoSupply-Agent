package com.motorparts.inventory.transaction;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class InventoryTransactionService {
    private final InventoryTransactionMapper mapper;

    public Page<InventoryTransaction> page(long current, long size, Long partId, String transactionType,
                                           String sourceType, Long sourceId, Long operatorId,
                                           LocalDateTime startTime, LocalDateTime endTime, String operationId) {
        LambdaQueryWrapper<InventoryTransaction> query = filters(partId, transactionType, sourceType, sourceId,
                operatorId, startTime, endTime, operationId);
        query.orderByDesc(InventoryTransaction::getOccurredAt).orderByDesc(InventoryTransaction::getId);
        return mapper.selectPage(new Page<>(current, size), query);
    }

    public InventoryTransaction get(Long id) {
        return id == null ? null : mapper.selectById(id);
    }

    public List<InventoryTransaction> listForPart(Long partId, LocalDateTime startTime, LocalDateTime endTime) {
        LambdaQueryWrapper<InventoryTransaction> query = filters(partId, null, null, null, null,
                startTime, endTime, null);
        query.orderByDesc(InventoryTransaction::getOccurredAt).orderByDesc(InventoryTransaction::getId);
        return mapper.selectList(query);
    }

    private static LambdaQueryWrapper<InventoryTransaction> filters(
            Long partId, String transactionType, String sourceType, Long sourceId, Long operatorId,
            LocalDateTime startTime, LocalDateTime endTime, String operationId) {
        LambdaQueryWrapper<InventoryTransaction> query = new LambdaQueryWrapper<>();
        query.eq(partId != null, InventoryTransaction::getPartId, partId)
                .eq(StringUtils.hasText(transactionType), InventoryTransaction::getTransactionType, transactionType)
                .eq(StringUtils.hasText(sourceType), InventoryTransaction::getSourceType, sourceType)
                .eq(sourceId != null, InventoryTransaction::getSourceId, sourceId)
                .eq(operatorId != null, InventoryTransaction::getOperatorId, operatorId)
                .ge(startTime != null, InventoryTransaction::getOccurredAt, startTime)
                .le(endTime != null, InventoryTransaction::getOccurredAt, endTime)
                .eq(StringUtils.hasText(operationId), InventoryTransaction::getOperationId, operationId);
        return query;
    }
}
