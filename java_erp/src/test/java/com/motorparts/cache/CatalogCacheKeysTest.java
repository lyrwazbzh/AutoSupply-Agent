package com.motorparts.cache;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;

class CatalogCacheKeysTest {
    private final CatalogCacheKeys keys = new CatalogCacheKeys();

    @Test
    void normalizesWhitespaceAndEmptySearchValues() {
        assertEquals(keys.search("火花塞"), keys.search("  火花塞  "));
        assertEquals("_", keys.search("   "));
        assertEquals("_", keys.search(null));
    }

    @Test
    void pageKeyUsesEveryParameterInStableOrder() {
        String base = keys.partPage(1L, 10L, "火花塞", "电气", 7L);
        assertEquals(base, keys.partPage(1L, 10L, " 火花塞 ", "电气", 7L));
        assertNotEquals(base, keys.partPage(2L, 10L, "火花塞", "电气", 7L));
        assertNotEquals(base, keys.partPage(1L, 20L, "火花塞", "电气", 7L));
    }
}
