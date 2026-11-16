package com.motorparts.supplier.quotation;

import com.motorparts.cache.CatalogCacheInvalidator;
import com.motorparts.common.exception.BusinessException;
import com.motorparts.entity.Part;
import com.motorparts.entity.Supplier;
import com.motorparts.mapper.PartMapper;
import com.motorparts.mapper.SupplierMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SupplierQuotationServiceTest {
    private SupplierPartMapper relationMapper;
    private PartMapper partMapper;
    private SupplierMapper supplierMapper;
    private CatalogCacheInvalidator cacheInvalidator;
    private SupplierQuotationService service;

    @BeforeEach
    void setUp() {
        relationMapper = mock(SupplierPartMapper.class);
        partMapper = mock(PartMapper.class);
        supplierMapper = mock(SupplierMapper.class);
        cacheInvalidator = mock(CatalogCacheInvalidator.class);
        service = new SupplierQuotationService(relationMapper, partMapper, supplierMapper, cacheInvalidator);
    }

    @Test
    void listsEnabledDefaultSupplierBeforeCheaperAlternatives() {
        Part part = part(10L, 2L, "120.00");
        SupplierPart cheaper = relation(1L, 1L, 10L, "90.00", true);
        SupplierPart defaultRelation = relation(2L, 2L, 10L, "120.00", true);
        SupplierPart inactiveSupplierQuote = relation(3L, 3L, 10L, "70.00", true);
        when(partMapper.selectById(10L)).thenReturn(part);
        when(relationMapper.selectList(any())).thenReturn(List.of(cheaper, defaultRelation, inactiveSupplierQuote));
        when(supplierMapper.selectBatchIds(any())).thenReturn(List.of(
                supplier(1L, "S-1", "低价供应商", 1), supplier(2L, "S-2", "默认供应商", 1),
                supplier(3L, "S-3", "已终止供应商", 2)));

        List<SupplierOptionView> result = service.listOptions(10L);

        assertEquals(List.of(2L, 1L, 3L), result.stream().map(SupplierOptionView::supplierId).toList());
        assertTrue(result.get(0).defaultSupplier());
        assertEquals(false, result.get(2).enabled());
    }

    @Test
    void rejectsEnabledQuoteForInactiveSupplier() {
        when(partMapper.selectById(10L)).thenReturn(part(10L, null, "100.00"));
        when(supplierMapper.selectById(3L)).thenReturn(supplier(3L, "S-3", "停用供应商", 2));
        SupplierPartRequests.Create request = new SupplierPartRequests.Create(
                3L, null, new BigDecimal("88.00"), 1, 3, null, null, true, false);

        assertThrows(BusinessException.class, () -> service.create(10L, request));
        verify(relationMapper, never()).insert(any());
    }

    @Test
    void settingQuoteAsDefaultUpdatesCompatibilityFieldsAndEvictsPartCache() {
        Part part = part(10L, 1L, "100.00");
        Supplier supplier = supplier(2L, "S-2", "新默认供应商", 1);
        when(partMapper.selectById(10L)).thenReturn(part);
        when(supplierMapper.selectById(2L)).thenReturn(supplier);
        when(relationMapper.selectOne(any())).thenReturn(null);
        when(relationMapper.insert(any())).thenAnswer(invocation -> {
            SupplierPart relation = invocation.getArgument(0);
            relation.setId(99L);
            return 1;
        });
        when(partMapper.updateById(any(Part.class))).thenReturn(1);
        SupplierPartRequests.Create request = new SupplierPartRequests.Create(
                2L, "ALT-10", new BigDecimal("95.00"), 5, 2, new BigDecimal("4.50"),
                null, true, true);

        SupplierOptionView created = service.create(10L, request);

        assertEquals(2L, created.supplierId());
        assertTrue(created.defaultSupplier());
        verify(partMapper).updateById(any(Part.class));
        verify(cacheInvalidator).evictParts();
    }

    @Test
    void refusesToDeleteCurrentDefaultSupplierRelation() {
        Part part = part(10L, 2L, "100.00");
        when(partMapper.selectById(10L)).thenReturn(part);
        when(relationMapper.selectOne(any())).thenReturn(relation(2L, 2L, 10L, "100.00", true));

        assertThrows(BusinessException.class, () -> service.delete(10L, 2L));
        verify(relationMapper, never()).deleteById(2L);
    }

    private static Part part(Long id, Long supplierId, String price) {
        Part part = new Part();
        part.setId(id);
        part.setPartCode("P-" + id);
        part.setName("零件" + id);
        part.setSupplierId(supplierId);
        part.setPurchasePrice(new BigDecimal(price));
        return part;
    }

    private static Supplier supplier(Long id, String code, String name, int status) {
        Supplier supplier = new Supplier();
        supplier.setId(id);
        supplier.setSupplierCode(code);
        supplier.setName(name);
        supplier.setStatus(status);
        return supplier;
    }

    private static SupplierPart relation(Long id, Long supplierId, Long partId, String price, boolean enabled) {
        SupplierPart relation = new SupplierPart();
        relation.setId(id);
        relation.setSupplierId(supplierId);
        relation.setPartId(partId);
        relation.setPurchasePrice(new BigDecimal(price));
        relation.setMinimumOrderQuantity(1);
        relation.setEnabled(enabled);
        return relation;
    }
}
