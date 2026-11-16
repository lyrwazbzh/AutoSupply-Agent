package com.motorparts.service.impl;

import com.motorparts.cache.CatalogCacheInvalidator;
import com.motorparts.cache.CatalogCacheKeys;
import com.motorparts.cache.CatalogCacheNames;
import com.motorparts.entity.Part;
import com.motorparts.mapper.PartMapper;
import com.motorparts.mapper.SupplierMapper;
import com.motorparts.service.PartService;
import com.motorparts.supplier.quotation.SupplierQuotationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.concurrent.ConcurrentMapCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.junit.jupiter.SpringJUnitConfig;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@SpringJUnitConfig(CatalogServiceCachingTest.Config.class)
class CatalogServiceCachingTest {
    @Autowired private PartService parts;
    @Autowired private PartMapper partMapper;
    @Autowired private CacheManager cacheManager;

    @BeforeEach
    void resetState() {
        reset(partMapper);
        CatalogCacheNames.ALL.forEach(name -> {
            if (cacheManager.getCache(name) != null) cacheManager.getCache(name).clear();
        });
    }

    @Test
    void secondDetailReadUsesCacheAndNullResultIsNotCached() {
        Part part = part(1L, "旧火花塞");
        when(partMapper.selectById(1L)).thenReturn(part);

        assertEquals("旧火花塞", parts.getPart(1L).getName());
        assertEquals("旧火花塞", parts.getPart(1L).getName());
        verify(partMapper, times(1)).selectById(1L);

        when(partMapper.selectById(2L)).thenReturn(null);
        assertNull(parts.getPart(2L));
        assertNull(parts.getPart(2L));
        verify(partMapper, times(2)).selectById(2L);
    }

    @Test
    void successfulUpdateEvictsCachedPartButFailedUpdateDoesNot() {
        Part oldPart = part(1L, "旧火花塞");
        Part updated = part(1L, "新火花塞");
        when(partMapper.selectById(1L)).thenReturn(oldPart, updated);
        when(partMapper.updateById(any(Part.class))).thenReturn(1);

        assertEquals("旧火花塞", parts.getPart(1L).getName());
        parts.updatePart(updated);
        assertEquals("新火花塞", parts.getPart(1L).getName());
        verify(partMapper, times(3)).selectById(1L);

        when(partMapper.updateById(any(Part.class))).thenReturn(0);
        parts.updatePart(part(1L, "失败修改"));
        assertEquals("新火花塞", parts.getPart(1L).getName());
        verify(partMapper, times(3)).selectById(1L);
    }

    private static Part part(Long id, String name) {
        Part part = new Part();
        part.setId(id);
        part.setPartCode("P-" + id);
        part.setName(name);
        return part;
    }

    @Configuration
    @EnableCaching(proxyTargetClass = true)
    @Import({PartServiceImpl.class, SupplierServiceImpl.class,
            CatalogCacheKeys.class, CatalogCacheInvalidator.class})
    static class Config {
        @Bean
        CacheManager cacheManager() {
            return new ConcurrentMapCacheManager(CatalogCacheNames.ALL.toArray(String[]::new));
        }

        @Bean
        PartMapper partMapper() {
            return mock(PartMapper.class);
        }

        @Bean
        SupplierMapper supplierMapper() {
            return mock(SupplierMapper.class);
        }

        @Bean
        SupplierQuotationService supplierQuotationService() {
            return mock(SupplierQuotationService.class);
        }
    }
}
