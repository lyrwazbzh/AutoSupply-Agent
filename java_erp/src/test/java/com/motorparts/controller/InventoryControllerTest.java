package com.motorparts.controller;

import com.motorparts.common.Result;
import com.motorparts.dto.InventoryWithPart;
import com.motorparts.inventory.transaction.InventoryCommandService;
import com.motorparts.service.InventoryService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.Map;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.doReturn;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InventoryControllerTest {

    private MockMvc mockMvc;
    private InventoryService inventoryService;
    private InventoryCommandService inventoryCommandService;

    @BeforeEach
    void setUp() {
        inventoryService = mock(InventoryService.class);
        inventoryCommandService = mock(InventoryCommandService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InventoryController(inventoryService, inventoryCommandService))
                .build();
    }

    @Test
    void inboundReplaysCompletedOperationWithoutMutatingInventory() throws Exception {
        doReturn(Result.success(Map.of("replayed", true), "已回放"))
                .when(inventoryCommandService).inbound(1L, 2, null, "op-1", null, null);

        mockMvc.perform(post("/api/inventory/inbound")
                        .param("partId", "1")
                        .param("quantity", "2")
                        .header("X-Operation-Id", "op-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.replayed").value(true));

        verifyNoInteractions(inventoryService);
        verify(inventoryCommandService).inbound(1L, 2, null, "op-1", null, null);
    }

    @Test
    void inboundPersistsOperationResultOnSuccess() throws Exception {
        InventoryWithPart view = new InventoryWithPart();
        doReturn(Result.success(view, "入库成功"))
                .when(inventoryCommandService).inbound(1L, 2, "A-01", "op-in", null, null);

        mockMvc.perform(post("/api/inventory/inbound")
                        .param("partId", "1")
                        .param("quantity", "2")
                        .param("warehouseLocation", "A-01")
                        .param("operationId", "op-in"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.message").value("入库成功"));

        verify(inventoryCommandService).inbound(1L, 2, "A-01", "op-in", null, null);
    }

    @Test
    void inboundFailureIsNotRecordedAsCompleted() throws Exception {
        doReturn(Result.error()).when(inventoryCommandService)
                .inbound(1L, 2, null, null, null, null);

        mockMvc.perform(post("/api/inventory/inbound")
                        .param("partId", "1")
                        .param("quantity", "2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(500));

        verify(inventoryCommandService).inbound(1L, 2, null, null, null, null);
    }

    @Test
    void outboundReplaysCompletedOperationWithoutMutatingInventory() throws Exception {
        doReturn(Result.success(Map.of("replayed", true))).when(inventoryCommandService)
                .outbound(1L, 2, "op-out", null, null);

        mockMvc.perform(post("/api/inventory/outbound")
                        .param("partId", "1")
                        .param("quantity", "2")
                        .header("X-Operation-Id", "op-out"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200));

        verifyNoInteractions(inventoryService);
    }

    @Test
    void outboundPersistsOperationResultOnSuccess() throws Exception {
        doReturn(Result.success(new InventoryWithPart(), "出库成功")).when(inventoryCommandService)
                .outbound(1L, 2, "op-out-success", null, null);

        mockMvc.perform(post("/api/inventory/outbound")
                        .param("partId", "1")
                        .param("quantity", "2")
                        .param("operationId", "op-out-success"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.message").value("出库成功"));

        verify(inventoryCommandService).outbound(1L, 2, "op-out-success", null, null);
    }

    @Test
    void outboundReturnsInsufficientInventoryWithoutCompletingOperation() throws Exception {
        doReturn(Result.error(com.motorparts.common.enums.ResultCode.INSUFFICIENT_INVENTORY))
                .when(inventoryCommandService).outbound(1L, 99, "op-insufficient", null, null);

        mockMvc.perform(post("/api/inventory/outbound")
                        .param("partId", "1")
                        .param("quantity", "99")
                        .param("operationId", "op-insufficient"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(603));

        verify(inventoryCommandService).outbound(1L, 99, "op-insufficient", null, null);
    }
}
