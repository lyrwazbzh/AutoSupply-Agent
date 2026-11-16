package com.motorparts.procurement.receiving;

import com.motorparts.common.Result;
import com.motorparts.entity.Inventory;
import com.motorparts.entity.OrderDetail;
import com.motorparts.entity.Part;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.entity.PurchaseOrderWithDetails;
import com.motorparts.inventory.transaction.InventoryTransaction;
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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class OrderReceivingServiceTest {
    private PurchaseOrderMapper orderMapper;
    private OrderDetailMapper detailMapper;
    private PartMapper partMapper;
    private InventoryMapper inventoryMapper;
    private InventoryTransactionMapper transactionMapper;
    private SupplierPartMapper supplierPartMapper;
    private ReplenishmentTaskMapper replenishmentTaskMapper;
    private PurchaseOrderService orderService;
    private ErpOperationService operationService;
    private OrderReceivingService service;

    @BeforeEach
    void setUp() {
        orderMapper = mock(PurchaseOrderMapper.class);
        detailMapper = mock(OrderDetailMapper.class);
        partMapper = mock(PartMapper.class);
        inventoryMapper = mock(InventoryMapper.class);
        transactionMapper = mock(InventoryTransactionMapper.class);
        supplierPartMapper = mock(SupplierPartMapper.class);
        replenishmentTaskMapper = mock(ReplenishmentTaskMapper.class);
        orderService = mock(PurchaseOrderService.class);
        operationService = mock(ErpOperationService.class);
        service = new OrderReceivingService(orderMapper, detailMapper, partMapper, inventoryMapper,
                transactionMapper, supplierPartMapper, replenishmentTaskMapper, orderService, operationService);
    }

    @Test
    void replayReturnsOriginalResultWithoutLockingOrder() {
        doReturn(Result.success(Map.of("replayed", true))).when(operationService).replay("receive-1");

        Result<?> result = service.receive(9L, null, "receive-1", 5L);

        assertEquals(200, result.getCode());
        verifyNoInteractions(orderMapper, inventoryMapper, transactionMapper);
    }

    @Test
    void rejectsOrderThatIsNotPurchasing() {
        PurchaseOrder order = order(9L, 2);
        when(orderMapper.selectByIdForUpdate(9L)).thenReturn(order);

        Result<?> result = service.receive(9L, null, "receive-2", 5L);

        assertEquals(604, result.getCode());
        verifyNoInteractions(detailMapper, inventoryMapper, transactionMapper);
        verify(operationService, never()).complete(any(), any());
    }

    @Test
    void receivesWholeOrderAndWritesPurchaseReceiptLedger() {
        PurchaseOrder order = order(9L, 3);
        order.setSupplierId(11L);
        OrderDetail detail = OrderDetail.builder().orderId(9L).partId(2L).quantity(4).build();
        Part part = new Part();
        part.setId(2L);
        Inventory inventory = new Inventory();
        inventory.setId(20L);
        inventory.setPartId(2L);
        inventory.setCurrentQuantity(6);
        inventory.setWarehouseLocation("A-01");
        OrderReceiveRequest request = new OrderReceiveRequest();
        request.setActualArrivalDate(LocalDate.of(2026, 11, 9));
        request.setWarehouseLocation("B-02");
        request.setRemark("外观检查通过");
        when(orderMapper.selectByIdForUpdate(9L)).thenReturn(order);
        when(detailMapper.selectByOrderIdForUpdate(9L)).thenReturn(List.of(detail));
        when(partMapper.selectById(2L)).thenReturn(part);
        when(inventoryMapper.insertEmptyIfAbsent(2L, "B-02")).thenReturn(0);
        when(inventoryMapper.selectByPartIdForUpdate(2L)).thenReturn(inventory);
        when(inventoryMapper.applyInbound(any(), any(), any(), any())).thenReturn(1);
        when(transactionMapper.insert(any())).thenReturn(1);
        when(orderMapper.markReceived(9L, LocalDate.of(2026, 11, 9))).thenReturn(1);
        when(orderService.loadOrderWithDetails(9L)).thenReturn(new PurchaseOrderWithDetails());

        Result<?> result = service.receive(9L, request, "receive-3", 5L);

        assertEquals(200, result.getCode());
        assertInstanceOf(OrderReceiveResponse.class, result.getData());
        OrderReceiveResponse response = (OrderReceiveResponse) result.getData();
        assertEquals(4, response.status());
        assertEquals(1, response.receivedLines().size());
        assertEquals(10, response.receivedLines().get(0).afterQuantity());
        ArgumentCaptor<InventoryTransaction> captor = ArgumentCaptor.forClass(InventoryTransaction.class);
        verify(transactionMapper).insert(captor.capture());
        assertEquals(InventoryTransactionType.PURCHASE_RECEIPT.name(), captor.getValue().getTransactionType());
        assertEquals("PURCHASE_ORDER", captor.getValue().getSourceType());
        assertEquals(9L, captor.getValue().getSourceId());
        assertEquals(6, captor.getValue().getBeforeQuantity());
        assertEquals(10, captor.getValue().getAfterQuantity());
        verify(supplierPartMapper).touchSupplierPurchase(any(), any(), any());
        verify(orderMapper).markReceived(9L, LocalDate.of(2026, 11, 9));
        verify(replenishmentTaskMapper).completeByRelatedOrderId(any(), any());
        verify(operationService).complete(any(), any());
    }

    private static PurchaseOrder order(Long id, int status) {
        PurchaseOrder order = new PurchaseOrder();
        order.setId(id);
        order.setOrderNumber("PO-" + id);
        order.setStatus(status);
        return order;
    }
}
