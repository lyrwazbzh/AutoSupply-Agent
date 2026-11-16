package com.motorparts.replenishment;

import com.motorparts.common.Result;
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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ReplenishmentServiceTest {
    private ReplenishmentTaskMapper taskMapper;
    private ReplenishmentInspectionMapper inspectionMapper;
    private ReplenishmentQueryMapper queryMapper;
    private InventoryMapper inventoryMapper;
    private PartMapper partMapper;
    private SupplierMapper supplierMapper;
    private SupplierPartMapper supplierPartMapper;
    private PurchaseOrderService orderService;
    private ErpOperationService operationService;
    private ReplenishmentService service;

    @BeforeEach
    void setUp() {
        taskMapper = mock(ReplenishmentTaskMapper.class);
        inspectionMapper = mock(ReplenishmentInspectionMapper.class);
        queryMapper = mock(ReplenishmentQueryMapper.class);
        inventoryMapper = mock(InventoryMapper.class);
        partMapper = mock(PartMapper.class);
        supplierMapper = mock(SupplierMapper.class);
        supplierPartMapper = mock(SupplierPartMapper.class);
        orderService = mock(PurchaseOrderService.class);
        operationService = mock(ErpOperationService.class);
        service = new ReplenishmentService(taskMapper, inspectionMapper, queryMapper, inventoryMapper,
                partMapper, supplierMapper, supplierPartMapper, orderService, operationService);
        ReflectionTestUtils.setField(service, "targetStockMultiplier", 2);
    }

    @Test
    void suggestionUsesTargetGapButNeverDropsBelowMoq() {
        assertEquals(15, ReplenishmentService.calculateSuggestedQuantity(5, 10, 3, 2));
        assertEquals(5, ReplenishmentService.calculateSuggestedQuantity(19, 10, 5, 2));
    }

    @Test
    void inspectionSkipsPartThatAlreadyHasActiveTask() {
        LowStockCandidate candidate = candidate(1L, 2, 10);
        when(queryMapper.selectLowStockCandidates()).thenReturn(List.of(candidate));
        when(queryMapper.countActiveParts()).thenReturn(1);
        when(taskMapper.selectActiveByPartId(1L)).thenReturn(task(8L, 1L, ReplenishmentTaskStatus.PENDING));
        when(inspectionMapper.insert(any())).thenReturn(1);

        Result<?> result = service.inspect("MANUAL", "inspect-1", 3L);

        assertEquals(200, result.getCode());
        ReplenishmentInspectionResult data = assertInstanceOf(ReplenishmentInspectionResult.class, result.getData());
        assertEquals(0, data.createdCount());
        assertEquals(1, data.skippedActiveCount());
        verify(taskMapper, never()).insert(any());
        verify(operationService).complete(any(), any());
    }

    @Test
    void inspectionCreatesDeterministicTaskWithDefaultActiveSupplier() {
        LowStockCandidate candidate = candidate(1L, 2, 10);
        Part part = part(1L, 11L);
        SupplierPart quotation = quotation(1L, 11L, 6, "20.00");
        Supplier supplier = supplier(11L, 1);
        when(queryMapper.selectLowStockCandidates()).thenReturn(List.of(candidate));
        when(queryMapper.countActiveParts()).thenReturn(4);
        when(partMapper.selectById(1L)).thenReturn(part);
        when(supplierPartMapper.selectList(any())).thenReturn(List.of(quotation));
        when(supplierMapper.selectById(11L)).thenReturn(supplier);
        when(taskMapper.insert(any())).thenAnswer(invocation -> {
            ReplenishmentTask inserted = invocation.getArgument(0);
            inserted.setId(101L);
            return 1;
        });
        when(inspectionMapper.insert(any())).thenReturn(1);

        Result<?> result = service.inspect("SCHEDULED", null, null);

        ReplenishmentInspectionResult data = assertInstanceOf(ReplenishmentInspectionResult.class, result.getData());
        assertEquals(1, data.createdCount());
        assertEquals(List.of(101L), data.createdTaskIds());
        ArgumentCaptor<ReplenishmentTask> captor = ArgumentCaptor.forClass(ReplenishmentTask.class);
        verify(taskMapper).insert(captor.capture());
        assertEquals(18, captor.getValue().getSuggestedQuantity());
        assertEquals(11L, captor.getValue().getPreferredSupplierId());
        assertEquals(ReplenishmentSource.AUTO_INSPECTION.name(), captor.getValue().getSource());
        assertNull(captor.getValue().getOperationId());
    }

    @Test
    void createOrderUsesQuotationAndLinksTaskAtomically() {
        ReplenishmentTask task = task(8L, 1L, ReplenishmentTaskStatus.PENDING);
        task.setTaskNo("RPT-8");
        task.setSuggestedQuantity(12);
        task.setPreferredSupplierId(11L);
        Part part = part(1L, 11L);
        SupplierPart quotation = quotation(1L, 11L, 5, "22.50");
        when(taskMapper.selectByIdForUpdate(8L)).thenReturn(task);
        when(partMapper.selectById(1L)).thenReturn(part);
        when(supplierPartMapper.selectList(any())).thenReturn(List.of(quotation));
        when(supplierMapper.selectById(11L)).thenReturn(supplier(11L, 1));
        PurchaseOrderWithDetails created = new PurchaseOrderWithDetails();
        created.setId(77L);
        doReturn(Result.success(created)).when(orderService).createOrderIdempotent(any(), isNull());
        when(taskMapper.markOrderCreated(any(), any(), any(), any(), any())).thenReturn(1);
        ReplenishmentTask updated = task(8L, 1L, ReplenishmentTaskStatus.ORDER_CREATED);
        updated.setRelatedOrderId(77L);
        when(taskMapper.selectById(8L)).thenReturn(updated);

        Result<?> result = service.createOrder(8L, null, "task-order-8", 3L);

        assertEquals(200, result.getCode());
        assertInstanceOf(ReplenishmentOrderResult.class, result.getData());
        ArgumentCaptor<PurchaseOrderWithDetails> captor = ArgumentCaptor.forClass(PurchaseOrderWithDetails.class);
        verify(orderService).createOrderIdempotent(captor.capture(), isNull());
        PurchaseOrderWithDetails order = captor.getValue();
        assertEquals(11L, order.getSupplierId());
        assertEquals("REPLENISHMENT-TASK-8", order.getIdempotencyKey());
        assertEquals(12, order.getOrderDetail().get(0).getQuantity());
        assertEquals(new BigDecimal("22.50"), order.getOrderDetail().get(0).getUnitPrice());
        verify(taskMapper).markOrderCreated(any(), any(), any(), any(), any());
        verify(operationService).complete(any(), any());
    }

    private static LowStockCandidate candidate(Long partId, int current, int safety) {
        LowStockCandidate value = new LowStockCandidate();
        value.setPartId(partId);
        value.setCurrentQuantity(current);
        value.setSafetyStock(safety);
        return value;
    }

    private static Part part(Long id, Long supplierId) {
        Part part = new Part();
        part.setId(id);
        part.setSupplierId(supplierId);
        part.setStockWarningValue(10);
        return part;
    }

    private static Supplier supplier(Long id, int status) {
        Supplier supplier = new Supplier();
        supplier.setId(id);
        supplier.setStatus(status);
        return supplier;
    }

    private static SupplierPart quotation(Long partId, Long supplierId, int moq, String price) {
        SupplierPart relation = new SupplierPart();
        relation.setPartId(partId);
        relation.setSupplierId(supplierId);
        relation.setMinimumOrderQuantity(moq);
        relation.setPurchasePrice(new BigDecimal(price));
        relation.setEnabled(true);
        return relation;
    }

    private static ReplenishmentTask task(Long id, Long partId, ReplenishmentTaskStatus status) {
        ReplenishmentTask task = new ReplenishmentTask();
        task.setId(id);
        task.setPartId(partId);
        task.setStatus(status.name());
        return task;
    }
}
