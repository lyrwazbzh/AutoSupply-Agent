package com.motorparts.cache;

import lombok.RequiredArgsConstructor;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
@RequiredArgsConstructor
public class CatalogCacheInvalidator {
    private final CacheManager cacheManager;

    public void evictParts() {
        clear(CatalogCacheNames.PART_CACHES);
    }

    public void evictSuppliers() {
        clear(CatalogCacheNames.SUPPLIER_CACHES);
    }

    private void clear(List<String> names) {
        for (String name : names) {
            Cache cache = cacheManager.getCache(name);
            if (cache != null) {
                cache.clear();
            }
        }
    }
}
