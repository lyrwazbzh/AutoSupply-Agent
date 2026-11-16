package com.motorparts.procurement.returnorder;

import com.motorparts.common.Result;
import com.motorparts.entity.Inventory;
import com.motorparts.entity.OrderDetail;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.inventory.transaction.InventoryTransaction;
import com.motorparts.inventory.transaction.InventoryTransactionMapper;
import com.motorparts.inventory.transaction.InventoryTransactionType;
import com.motorparts.mapper.InventoryMapper;
import com.motorparts.mapper.OrderDetailMapper;
import com.motorparts.mapper.PurchaseOrderMapper;
import com.motorparts.service.ErpOperationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class PurchaseReturnServiceTest {
    private PurchaseReturnMapper returnMapper;
    private PurchaseOrderMapper orderMapper;
    private OrderDetailMapper detailMapper;
    private InventoryMapper inventoryMapper;
    private InventoryTransactionMapper transactionMapper;
    private ErpOperationService operationService;
    private PurchaseReturnService service;

    @BeforeEach
    void setUp() {
        returnMapper = mock(PurchaseReturnMapper.class);
        orderMapper = mock(PurchaseOrderMapper.class);
        detailMapper = mock(OrderDetailMapper.class);
        inventoryMapper = mock(InventoryMapper.class);
        transactionMapper = mock(InventoryTransactionMapper.class);
        operationService = mock(ErpOperationService.class);
        service = new PurchaseReturnService(returnMapper, orderMapper, detailMapper, inventoryMapper,
                transactionMapper, operationService);
    }

    @Test
    void replayReturnsOriginalResultWithoutTouchingReturnData() {
        doReturn(Result.success(Map.of("replayed", true))).when(operationService).replay("return-replay");

        Result<?> result = service.confirm(8L, "return-replay", 3L);

        assertEquals(200, result.getCode());
        verifyNoInteractions(returnMapper, orderMapper, inventoryMapper, transactionMapper);
    }

    @Test
    void createsPendingReturnForStoredPurchaseOrder() {
        PurchaseOrder order = order(9L, 4);
        when(orderMapper.selectByIdForUpdate(9L)).thenReturn(order);
        when(detailMapper.selectByOrderIdForUpdate(9L)).thenReturn(List.of(detail(9L, 2L, 10)));
        when(returnMapper.sumConfirmedQuantity(9L, 2L)).thenReturn(2);
        doAnswer(invocation -> {
            PurchaseReturn row = invocation.getArgument(0);
            row.setId(30L);
            return 1;
        }).when(returnMapper).insert(any(PurchaseReturn.class));

        Result<?> result = service.create(new PurchaseReturnRequests.Create(
                9L, 2L, 3, "quality_issue", "批次硬度不合格", "return-create-1"),
                "return-create-1", 5L);

        assertEquals(200, result.getCode());
        assertInstanceOf(PurchaseReturn.class, result.getData());
        PurchaseReturn created = (PurchaseReturn) result.getData();
        assertEquals(30L, created.getId());
        assertEquals(PurchaseReturnStatus.PENDING.name(), created.getStatus());
        assertEquals(PurchaseReturnReasonType.QUALITY_ISSUE.name(), created.getReasonType());
        assertEquals(5L, created.getCreatedBy());
        verify(operationService).complete("return-create-1", result);
    }

    @Test
    void rejectsCreateWhenPurchaseOrderIsNotStored() {
        when(orderMapper.selectByIdForUpdate(9L)).thenReturn(order(9L, 3));

        Result<?> result = service.create(new PurchaseReturnRequests.Create(
                9L, 2L, 3, "DAMAGED", "破损", "return-create-2"),
                "return-create-2", 5L);

        assertEquals(604, result.getCode());
        verifyNoInteractions(detailMapper, inventoryMapper, transactionMapper);
        verify(returnMapper, never()).insert(any());
        verify(operationService, never()).complete(any(), any());
    }

    @Test
    void confirmsReturnAndWritesPurchaseReturnLedger() {
        PurchaseReturn pending = pendingReturn(30L, 9L, 2L, 3);
        PurchaseReturn confirmed = pendingReturn(30L, 9L, 2L, 3);
        confirmed.setStatus(PurchaseReturnStatus.CONFIRMED.name());
        Inventory inventory = inventory(20L, 2L, 7, "A-01");
        when(returnMapper.selectByIdForUpdate(30L)).thenReturn(pending);
        when(orderMapper.selectByIdForUpdate(9L)).thenReturn(order(9L, 4));
        when(detailMapper.selectByOrderIdForUpdate(9L)).thenReturn(List.of(detail(9L, 2L, 10)));
        when(returnMapper.sumConfirmedQuantity(9L, 2L)).thenReturn(2);
        when(inventoryMapper.selectByPartIdForUpdate(2L)).thenReturn(inventory);
        when(inventoryMapper.applyOutbound(any(), any(), any(), any())).thenReturn(1);
        when(transactionMapper.insert(any())).thenReturn(1);
        when(returnMapper.markConfirmed(any(), any(), any(), any())).thenReturn(1);
        when(returnMapper.selectById(30L)).thenReturn(confirmed);

        Result<?> result = service.confirm(30L, "return-confirm-1", 6L);

        assertEquals(200, result.getCode());
        assertEquals(PurchaseReturnStatus.CONFIRMED.name(), ((PurchaseReturn) result.getData()).getStatus());
        verify(inventoryMapper).applyOutbound(any(), any(), any(), any());
        ArgumentCaptor<InventoryTransaction> captor = ArgumentCaptor.forClass(InventoryTransaction.class);
        verify(transactionMapper).insert(captor.capture());
        InventoryTransaction ledger = captor.getValue();
        assertEquals(InventoryTransactionType.PURCHASE_RETURN.name(), ledger.getTransactionType());
        assertEquals("PURCHASE_RETURN", ledger.getSourceType());
        assertEquals(30L, ledger.getSourceId());
        assertEquals(7, ledger.getBeforeQuantity());
        assertEquals(4, ledger.getAfterQuantity());
        assertEquals("return-confirm-1", ledger.getOperationId());
        verify(returnMapper).markConfirmed(any(), any(), any(), any());
        verify(operationService).complete("return-confirm-1", result);
    }

    @Test
    void rejectsConfirmWhenCumulativeReturnWouldExceedOrderedQuantity() {
        when(returnMapper.selectByIdForUpdate(30L)).thenReturn(pendingReturn(30L, 9L, 2L, 3));
        when(orderMapper.selectByIdForUpdate(9L)).thenReturn(order(9L, 4));
        when(detailMapper.selectByOrderIdForUpdate(9L)).thenReturn(List.of(detail(9L, 2L, 10)));
        when(returnMapper.sumConfirmedQuantity(9L, 2L)).thenReturn(8);

        Result<?> result = service.confirm(30L, "return-confirm-2", 6L);

        assertEquals(600, result.getCode());
        verifyNoInteractions(inventoryMapper, transactionMapper);
        verify(returnMapper, never()).markConfirmed(any(), any(), any(), any());
    }

    @Test
    void rejectsConfirmWhenInventoryIsInsufficient() {
        when(returnMapper.selectByIdForUpdate(30L)).thenReturn(pendingReturn(30L, 9L, 2L, 3));
        when(orderMapper.selectByIdForUpdate(9L)).thenReturn(order(9L, 4));
        when(detailMapper.selectByOrderIdForUpdate(9L)).thenReturn(List.of(detail(9L, 2L, 10)));
        when(returnMapper.sumConfirmedQuantity(9L, 2L)).thenReturn(1);
        when(inventoryMapper.selectByPartIdForUpdate(2L)).thenReturn(inventory(20L, 2L, 2, "A-01"));

        Result<?> result = service.confirm(30L, "return-confirm-3", 6L);

        assertEquals(603, result.getCode());
        verify(inventoryMapper, never()).applyOutbound(any(), any(), any(), any());
        verifyNoInteractions(transactionMapper);
        verify(returnMapper, never()).markConfirmed(any(), any(), any(), any());
    }

    private static PurchaseOrder order(Long id, int status) {
        PurchaseOrder order = new PurchaseOrder();
        order.setId(id);
        order.setStatus(status);
        return order;
    }

    private static OrderDetail detail(Long orderId, Long partId, int quantity) {
        return OrderDetail.builder().orderId(orderId).partId(partId).quantity(quantity)
                .unitPrice(BigDecimal.TEN).build();
    }

    private static PurchaseReturn pendingReturn(Long id, Long orderId, Long partId, int quantity) {
        PurchaseReturn row = new PurchaseReturn();
        row.setId(id);
        row.setPurchaseOrderId(orderId);
        row.setPartId(partId);
        row.setQuantity(quantity);
        row.setReasonType(PurchaseReturnReasonType.DAMAGED.name());
        row.setReason("运输破损");
        row.setStatus(PurchaseReturnStatus.PENDING.name());
        return row;
    }

    private static Inventory inventory(Long id, Long partId, int quantity, String location) {
        Inventory inventory = new Inventory();
        inventory.setId(id);
        inventory.setPartId(partId);
        inventory.setCurrentQuantity(quantity);
        inventory.setWarehouseLocation(location);
        return inventory;
    }
}
