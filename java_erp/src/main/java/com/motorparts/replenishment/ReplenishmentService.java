package com.motorparts.replenishment;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.entity.Inventory;
import com.motorparts.entity.OrderDetailWithPart;
import com.motorparts.entity.Part;
import com.motorparts.entity.PurchaseOrderWithDetails;
import com.motorparts.entity.Supplier;
import com.motorparts.mapper.InventoryMapper;
import com.motorparts.mapper.PartMapper;
import com.motorparts.mapper.SupplierMapper;
import com.motorparts.service.ErpOperationService;
import com.motorparts.service.PurchaseOrderService;
import com.motorparts.supplier.quotation.SupplierPart;
import com.motorparts.supplier.quotation.SupplierPartMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class ReplenishmentService {
    private final ReplenishmentTaskMapper taskMapper;
    private final ReplenishmentInspectionMapper inspectionMapper;
    private final ReplenishmentQueryMapper queryMapper;
    private final InventoryMapper inventoryMapper;
    private final PartMapper partMapper;
    private final SupplierMapper supplierMapper;
    private final SupplierPartMapper supplierPartMapper;
    private final PurchaseOrderService orderService;
    private final ErpOperationService operationService;

    @Value("${motorparts.replenishment.target-stock-multiplier:2}")
    private int targetStockMultiplier;

    public Page<ReplenishmentTask> page(long current, long size, String status, Long partId, String source) {
        LambdaQueryWrapper<ReplenishmentTask> query = new LambdaQueryWrapper<>();
        query.eq(StringUtils.hasText(status), ReplenishmentTask::getStatus, status)
                .eq(partId != null, ReplenishmentTask::getPartId, partId)
                .eq(StringUtils.hasText(source), ReplenishmentTask::getSource, source)
                .orderByDesc(ReplenishmentTask::getCreateTime)
                .orderByDesc(ReplenishmentTask::getId);
        return taskMapper.selectPage(new Page<>(current, size), query);
    }

    @Transactional(rollbackFor = Exception.class)
    public Result<?> create(ReplenishmentRequests.Create request, String operationId, Long actorId) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) return replay;
        if (request == null || request.partId() == null) {
            return Result.paramError("partId 不能为空");
        }
        Part part = partMapper.selectById(request.partId());
        if (part == null) return Result.error(ResultCode.DATA_NOT_EXISTS, "零部件不存在");
        ReplenishmentTask active = taskMapper.selectActiveByPartId(part.getId());
        if (active != null) {
            return Result.error(ResultCode.DATA_EXISTS.getCode(), "该零件已有未完成补货任务", active);
        }
        Inventory inventory = inventoryMapper.selectOne(new LambdaQueryWrapper<Inventory>()
                .eq(Inventory::getPartId, part.getId()));
        int current = inventory == null || inventory.getCurrentQuantity() == null ? 0 : inventory.getCurrentQuantity();
        int safety = inventory != null && inventory.getSafetyStock() != null
                ? inventory.getSafetyStock() : defaultSafety(part);
        SupplierPart preferred = selectSupplier(part, request.preferredSupplierId());
        if (request.preferredSupplierId() != null && preferred == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS, "指定供应商没有可用报价或供应商未处于合作中");
        }
        int moq = preferred == null || preferred.getMinimumOrderQuantity() == null
                ? 1 : preferred.getMinimumOrderQuantity();
        int suggested = request.suggestedQuantity() == null
                ? calculateSuggestedQuantity(current, safety, moq, targetStockMultiplier)
                : request.suggestedQuantity();
        if (suggested <= 0 || suggested < moq) {
            return Result.paramError("suggestedQuantity 必须大于 0 且不能小于最小采购量 " + moq);
        }
        ReplenishmentTask task = newTask(part.getId(), current, safety, suggested,
                preferred == null ? null : preferred.getSupplierId(), request.reason(),
                ReplenishmentSource.MANUAL, null, actorId, operationId);
        try {
            taskMapper.insert(task);
        } catch (DuplicateKeyException duplicate) {
            ReplenishmentTask raced = taskMapper.selectActiveByPartId(part.getId());
            return Result.error(ResultCode.DATA_EXISTS.getCode(), "该零件已有未完成补货任务", raced);
        }
        Result<?> result = Result.success(task, "补货任务创建成功");
        operationService.complete(operationId, result);
        return result;
    }

    @Transactional(rollbackFor = Exception.class)
    public Result<?> inspect(String invocationSource, String operationId, Long actorId) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) return replay;
        LocalDateTime startedAt = LocalDateTime.now();
        String runNo = "RPI-" + UUID.randomUUID().toString().replace("-", "");
        List<LowStockCandidate> candidates = queryMapper.selectLowStockCandidates();
        List<Long> createdIds = new ArrayList<>();
        int skipped = 0;
        int missingSupplier = 0;
        for (LowStockCandidate candidate : candidates) {
            if (taskMapper.selectActiveByPartId(candidate.getPartId()) != null) {
                skipped++;
                continue;
            }
            Part part = partMapper.selectById(candidate.getPartId());
            if (part == null) continue;
            SupplierPart preferred = selectSupplier(part, null);
            if (preferred == null) missingSupplier++;
            int moq = preferred == null || preferred.getMinimumOrderQuantity() == null
                    ? 1 : preferred.getMinimumOrderQuantity();
            int suggested = calculateSuggestedQuantity(candidate.getCurrentQuantity(), candidate.getSafetyStock(),
                    moq, targetStockMultiplier);
            ReplenishmentTask task = newTask(candidate.getPartId(), candidate.getCurrentQuantity(),
                    candidate.getSafetyStock(), suggested,
                    preferred == null ? null : preferred.getSupplierId(),
                    "库存低于安全库存，由巡检自动生成", ReplenishmentSource.AUTO_INSPECTION,
                    LocalDate.now(), actorId, null);
            try {
                taskMapper.insert(task);
                createdIds.add(task.getId());
            } catch (DuplicateKeyException duplicate) {
                skipped++;
            }
        }
        LocalDateTime completedAt = LocalDateTime.now();
        ReplenishmentInspection inspection = new ReplenishmentInspection();
        inspection.setRunNo(runNo);
        inspection.setSource(invocationSource);
        inspection.setStartedAt(startedAt);
        inspection.setCompletedAt(completedAt);
        inspection.setScannedCount(queryMapper.countActiveParts());
        inspection.setLowStockCount(candidates.size());
        inspection.setCreatedCount(createdIds.size());
        inspection.setSkippedActiveCount(skipped);
        inspection.setMissingSupplierCount(missingSupplier);
        inspection.setCreateTime(completedAt);
        inspectionMapper.insert(inspection);
        ReplenishmentInspectionResult data = new ReplenishmentInspectionResult(runNo,
                inspection.getScannedCount(), candidates.size(), createdIds.size(), skipped,
                missingSupplier, List.copyOf(createdIds));
        Result<?> result = Result.success(data, "库存巡检完成");
        operationService.complete(operationId, result);
        return result;
    }

    @Transactional(rollbackFor = Exception.class)
    public Result<?> createOrder(Long taskId, ReplenishmentRequests.CreateOrder request,
                                 String operationId, Long actorId) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) return replay;
        ReplenishmentTask task = taskMapper.selectByIdForUpdate(taskId);
        if (task == null) return Result.error(ResultCode.DATA_NOT_EXISTS, "补货任务不存在");
        if (!ReplenishmentTaskStatus.PENDING.name().equals(task.getStatus())) {
            return Result.error(ResultCode.BUSINESS_ERROR, "只有待处理补货任务可以转采购订单");
        }
        Part part = partMapper.selectById(task.getPartId());
        if (part == null) return Result.error(ResultCode.DATA_NOT_EXISTS, "零部件不存在");
        Long requestedSupplier = request != null && request.supplierId() != null
                ? request.supplierId() : task.getPreferredSupplierId();
        SupplierPart quotation = selectSupplier(part, requestedSupplier);
        if (quotation == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS, "请先为零件选择一个合作中供应商的有效报价");
        }
        int quantity = request != null && request.quantity() != null
                ? request.quantity() : task.getSuggestedQuantity();
        int moq = quotation.getMinimumOrderQuantity() == null ? 1 : quotation.getMinimumOrderQuantity();
        if (quantity <= 0 || quantity < moq) {
            return Result.paramError("quantity 必须大于 0 且不能小于最小采购量 " + moq);
        }
        BigDecimal unitPrice = quotation.getPurchasePrice() == null ? BigDecimal.ZERO : quotation.getPurchasePrice();
        PurchaseOrderWithDetails order = new PurchaseOrderWithDetails();
        order.setOrderNumber("PO-RP-" + taskId + "-" + LocalDateTime.now()
                .format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss")));
        order.setSupplierId(quotation.getSupplierId());
        order.setStatus(1);
        order.setExpectedDeliveryDate(request == null ? null : request.expectedDeliveryDate());
        order.setCreatedBy(actorId);
        order.setRemark(request == null ? "补货任务 " + task.getTaskNo() : request.remark());
        order.setIdempotencyKey("REPLENISHMENT-TASK-" + taskId);
        OrderDetailWithPart detail = new OrderDetailWithPart();
        detail.setPartId(task.getPartId());
        detail.setQuantity(quantity);
        detail.setUnitPrice(unitPrice);
        detail.setRemark("由补货任务 " + task.getTaskNo() + " 创建");
        order.setOrderDetail(List.of(detail));
        Result<?> orderResult = orderService.createOrderIdempotent(order, null);
        if (!ResultCode.SUCCESS.getCode().equals(orderResult.getCode())) {
            return orderResult;
        }
        if (!(orderResult.getData() instanceof PurchaseOrderWithDetails createdOrder)
                || createdOrder.getId() == null) {
            throw new IllegalStateException("补货任务创建采购订单后未返回订单ID");
        }
        if (taskMapper.markOrderCreated(taskId, createdOrder.getId(), quotation.getSupplierId(), quantity,
                LocalDateTime.now()) != 1) {
            throw new IllegalStateException("补货任务状态已变化，采购订单创建回滚");
        }
        ReplenishmentTask updated = taskMapper.selectById(taskId);
        Result<?> result = Result.success(new ReplenishmentOrderResult(updated, createdOrder), "补货任务已转采购订单");
        operationService.complete(operationId, result);
        return result;
    }

    @Transactional(rollbackFor = Exception.class)
    public Result<?> complete(Long taskId, String operationId) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) return replay;
        ReplenishmentTask task = taskMapper.selectByIdForUpdate(taskId);
        if (task == null) return Result.error(ResultCode.DATA_NOT_EXISTS);
        if (taskMapper.markCompleted(taskId, LocalDateTime.now()) != 1) {
            return Result.error(ResultCode.BUSINESS_ERROR, "只有未转订单的待处理任务可以人工完成");
        }
        Result<?> result = Result.success(taskMapper.selectById(taskId), "补货任务已完成");
        operationService.complete(operationId, result);
        return result;
    }

    @Transactional(rollbackFor = Exception.class)
    public Result<?> cancel(Long taskId, String operationId) {
        Result<?> replay = operationService.replay(operationId);
        if (replay != null) return replay;
        ReplenishmentTask task = taskMapper.selectByIdForUpdate(taskId);
        if (task == null) return Result.error(ResultCode.DATA_NOT_EXISTS);
        if (taskMapper.cancel(taskId, LocalDateTime.now()) != 1) {
            return Result.error(ResultCode.BUSINESS_ERROR, "只有待处理补货任务可以取消");
        }
        Result<?> result = Result.success(taskMapper.selectById(taskId), "补货任务已取消");
        operationService.complete(operationId, result);
        return result;
    }

    public static int calculateSuggestedQuantity(int current, int safety, int minimumOrderQuantity, int multiplier) {
        if (current < 0 || safety < 0 || minimumOrderQuantity < 1 || multiplier < 1) {
            throw new IllegalArgumentException("库存、最小采购量或补货倍数非法");
        }
        long targetGap = (long) safety * multiplier - current;
        long suggested = Math.max(targetGap, minimumOrderQuantity);
        if (suggested > Integer.MAX_VALUE) throw new ArithmeticException("建议采购量超出整数范围");
        return (int) suggested;
    }

    private SupplierPart selectSupplier(Part part, Long requestedSupplierId) {
        List<SupplierPart> relations = supplierPartMapper.selectList(new LambdaQueryWrapper<SupplierPart>()
                .eq(SupplierPart::getPartId, part.getId())
                .eq(SupplierPart::getEnabled, true));
        List<SupplierPart> active = relations.stream().filter(relation -> {
            Supplier supplier = supplierMapper.selectById(relation.getSupplierId());
            return supplier != null && Integer.valueOf(1).equals(supplier.getStatus());
        }).toList();
        if (requestedSupplierId != null) {
            return active.stream().filter(row -> requestedSupplierId.equals(row.getSupplierId())).findFirst().orElse(null);
        }
        Comparator<SupplierPart> order = Comparator
                .comparing((SupplierPart row) -> !row.getSupplierId().equals(part.getSupplierId()))
                .thenComparing(SupplierPart::getPurchasePrice, Comparator.nullsLast(Comparator.naturalOrder()))
                .thenComparing(SupplierPart::getLeadTimeDays, Comparator.nullsLast(Comparator.naturalOrder()))
                .thenComparing(SupplierPart::getQualityRating, Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(SupplierPart::getSupplierId);
        return active.stream().min(order).orElse(null);
    }

    private static ReplenishmentTask newTask(Long partId, int current, int safety, int suggested,
                                              Long supplierId, String reason, ReplenishmentSource source,
                                              LocalDate inspectionDate, Long actorId, String operationId) {
        LocalDateTime now = LocalDateTime.now();
        ReplenishmentTask task = new ReplenishmentTask();
        task.setTaskNo("RPT-" + UUID.randomUUID().toString().replace("-", ""));
        task.setPartId(partId);
        task.setCurrentQuantity(current);
        task.setSafetyStock(safety);
        task.setSuggestedQuantity(suggested);
        task.setPreferredSupplierId(supplierId);
        task.setReason(StringUtils.hasText(reason) ? reason.trim() : "人工创建补货任务");
        task.setStatus(ReplenishmentTaskStatus.PENDING.name());
        task.setSource(source.name());
        task.setInspectionDate(inspectionDate);
        task.setCreatedBy(actorId);
        task.setOperationId(StringUtils.hasText(operationId) ? operationId.trim() : null);
        task.setCreateTime(now);
        task.setUpdateTime(now);
        return task;
    }

    private static int defaultSafety(Part part) {
        return part.getStockWarningValue() == null ? 10 : Math.max(0, part.getStockWarningValue());
    }
}
