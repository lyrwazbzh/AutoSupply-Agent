package com.motorparts.inventory.transaction;

import com.motorparts.common.Result;
import com.motorparts.dto.InventoryWithPart;
import com.motorparts.entity.Inventory;
import com.motorparts.entity.Part;
import com.motorparts.mapper.InventoryMapper;
import com.motorparts.mapper.PartMapper;
import com.motorparts.service.ErpOperationService;
import com.motorparts.service.InventoryService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.mockito.ArgumentMatchers.any;

class InventoryCommandServiceTest {
    private InventoryMapper inventoryMapper;
    private InventoryTransactionMapper transactionMapper;
    private PartMapper partMapper;
    private InventoryService inventoryService;
    private ErpOperationService operationService;
    private InventoryCommandService service;

    @BeforeEach
    void setUp() {
        inventoryMapper = mock(InventoryMapper.class);
        transactionMapper = mock(InventoryTransactionMapper.class);
        partMapper = mock(PartMapper.class);
        inventoryService = mock(InventoryService.class);
        operationService = mock(ErpOperationService.class);
        service = new InventoryCommandService(inventoryMapper, transactionMapper, partMapper,
                inventoryService, operationService);
    }

    @Test
    void replayDoesNotTouchInventoryOrLedger() {
        doReturn(Result.success(Map.of("replayed", true))).when(operationService).replay("op-replay");

        Result<?> result = service.inbound(1L, 2, null, "op-replay", 7L, null);

        assertEquals(200, result.getCode());
        verifyNoInteractions(inventoryMapper, transactionMapper, partMapper, inventoryService);
        verify(operationService, never()).complete(any(), any());
    }

    @Test
    void inboundPersistsBeforeAfterLedgerAndOperationInOrder() {
        Part part = new Part();
        part.setId(1L);
        Inventory inventory = inventory(10L, 1L, 5, "A-01");
        InventoryWithPart view = new InventoryWithPart();
        when(partMapper.selectById(1L)).thenReturn(part);
        when(inventoryMapper.insertEmptyIfAbsent(1L, "B-02")).thenReturn(1);
        when(inventoryMapper.selectByPartIdForUpdate(1L)).thenReturn(inventory);
        when(inventoryMapper.applyInbound(any(), any(), any(), any())).thenReturn(1);
        when(transactionMapper.insert(any())).thenReturn(1);
        when(inventoryService.getInventoryWithPartByPartId(1L)).thenReturn(view);

        Result<?> result = service.inbound(1L, 3, "B-02", "op-in", 7L, "盘点补录");

        assertEquals(200, result.getCode());
        ArgumentCaptor<InventoryTransaction> captor = ArgumentCaptor.forClass(InventoryTransaction.class);
        verify(transactionMapper).insert(captor.capture());
        InventoryTransaction row = captor.getValue();
        assertEquals(InventoryTransactionType.MANUAL_INBOUND.name(), row.getTransactionType());
        assertEquals(5, row.getBeforeQuantity());
        assertEquals(8, row.getAfterQuantity());
        assertEquals(3, row.getQuantity());
        assertEquals("op-in", row.getOperationId());
        assertEquals(7L, row.getOperatorId());
        assertEquals("B-02", row.getWarehouseLocation());
        InOrder order = inOrder(inventoryMapper, transactionMapper, operationService);
        order.verify(inventoryMapper).applyInbound(any(), any(), any(), any());
        order.verify(transactionMapper).insert(any());
        order.verify(operationService).complete(any(), any());
    }

    @Test
    void outboundRejectsInsufficientStockWithoutLedgerOrCompletion() {
        when(inventoryMapper.selectByPartIdForUpdate(1L)).thenReturn(inventory(10L, 1L, 1, "A-01"));

        Result<?> result = service.outbound(1L, 2, "op-out", 7L, null);

        assertEquals(603, result.getCode());
        assertNull(result.getData());
        verifyNoInteractions(transactionMapper);
        verify(operationService, never()).complete(any(), any());
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
