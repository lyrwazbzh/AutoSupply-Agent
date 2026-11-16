package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.mapper.OrderDetailMapper;
import com.motorparts.mapper.OrderIdempotencyMapper;
import com.motorparts.mapper.PartMapper;
import com.motorparts.mapper.PurchaseOrderMapper;
import com.motorparts.mapper.SupplierMapper;
import com.motorparts.procurement.expiry.OrderExpiryTaskService;
import com.motorparts.service.ErpOperationService;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PurchaseOrderServiceImplTest {
    private PurchaseOrderMapper orderMapper;
    private OrderDetailMapper orderDetailMapper;
    private PurchaseOrderServiceImpl service;

    @BeforeAll
    static void initializeMybatisMetadata() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), PurchaseOrder.class);
    }

    @BeforeEach
    void setUp() {
        orderMapper = mock(PurchaseOrderMapper.class);
        orderDetailMapper = mock(OrderDetailMapper.class);
        service = new PurchaseOrderServiceImpl(
                orderDetailMapper, mock(PartMapper.class), mock(SupplierMapper.class),
                mock(OrderIdempotencyMapper.class), mock(ErpOperationService.class), mock(OrderExpiryTaskService.class));
        ReflectionTestUtils.setField(service, "baseMapper", orderMapper);
    }

    @Test
    void storedStatusCannotBypassReceivingWorkflow() {
        PurchaseOrder order = new PurchaseOrder();
        order.setId(1L);
        order.setStatus(3);
        when(orderMapper.selectById(1L)).thenReturn(order);

        assertFalse(service.updateOrderStatus(1L, 4));

        verify(orderMapper, never()).update(any(), any());
    }

    @Test
    void legacyZeroStatusIsRejectedBeforeExistingOrderIsDeleted() {
        PurchaseOrder order = new PurchaseOrder();
        order.setId(1L);
        order.setStatus(0);
        PurchaseOrder existing = new PurchaseOrder();
        existing.setId(1L);
        existing.setStatus(1);
        when(orderMapper.selectById(1L)).thenReturn(existing);

        assertFalse(service.updateById(order));

        verify(orderDetailMapper, never()).physicalDeleteByOrderId(any());
    }
}
