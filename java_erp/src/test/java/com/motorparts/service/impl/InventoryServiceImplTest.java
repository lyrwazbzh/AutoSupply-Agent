package com.motorparts.service.impl;

import com.motorparts.entity.Inventory;
import com.motorparts.entity.Part;
import com.motorparts.mapper.InventoryMapper;
import com.motorparts.mapper.PartMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InventoryServiceImplTest {

    private final InventoryMapper inventoryMapper = mock(InventoryMapper.class);
    private final PartMapper partMapper = mock(PartMapper.class);
    private InventoryServiceImpl service;

    @BeforeAll
    static void initializeMybatisMetadata() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Inventory.class);
    }

    @BeforeEach
    void setUp() {
        service = new InventoryServiceImpl();
        ReflectionTestUtils.setField(service, "baseMapper", inventoryMapper);
        ReflectionTestUtils.setField(service, "partMapper", partMapper);
    }

    @Test
    void rejectsInvalidQuantitiesBeforeAccessingDatabase() {
        assertFalse(service.inbound(1L, 0, null));
        assertFalse(service.outbound(1L, -1));
        verify(inventoryMapper, never()).selectOne(any());
    }

    @Test
    void inboundRejectsUnknownPart() {
        when(partMapper.selectById(9L)).thenReturn(null);

        assertFalse(service.inbound(9L, 2, null));
        verify(inventoryMapper, never()).insert(any());
    }

    @Test
    void outboundRejectsMissingInventory() {
        when(inventoryMapper.selectOne(any())).thenReturn(null);

        assertFalse(service.outbound(1L, 2));
    }

    @Test
    void outboundUsesMysqlCas() {
        Inventory current = new Inventory();
        current.setId(10L);
        current.setPartId(1L);
        current.setCurrentQuantity(5);
        when(inventoryMapper.selectOne(any())).thenReturn(current);
        when(inventoryMapper.update(any(), any())).thenReturn(1);

        assertTrue(service.outbound(1L, 2));
        verify(inventoryMapper).update(any(), any());
    }

    @Test
    void outboundReportsCasFailure() {
        Inventory current = new Inventory();
        current.setId(10L);
        current.setPartId(1L);
        current.setCurrentQuantity(1);
        when(inventoryMapper.selectOne(any())).thenReturn(current);
        when(inventoryMapper.update(any(), any())).thenReturn(0);

        assertFalse(service.outbound(1L, 1));
    }

    @Test
    void inboundCreatesInventoryWhenPartExists() {
        Part part = new Part();
        part.setId(1L);
        when(partMapper.selectById(1L)).thenReturn(part);
        when(inventoryMapper.selectOne(any())).thenReturn(null);
        when(inventoryMapper.insert(any(Inventory.class))).thenReturn(1);

        assertTrue(service.inbound(1L, 3, "A-01"));
        verify(inventoryMapper).insert(any(Inventory.class));
    }
}
