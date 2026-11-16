package com.motorparts.cache;

import java.util.List;

public final class CatalogCacheNames {
    public static final String PART_DETAIL = "part-detail";
    public static final String PART_PAGE = "part-page";
    public static final String PART_SEARCH = "part-search";
    public static final String PART_BY_SUPPLIER = "part-by-supplier";

    public static final String SUPPLIER_DETAIL = "supplier-detail";
    public static final String SUPPLIER_PAGE = "supplier-page";
    public static final String SUPPLIER_SEARCH = "supplier-search";

    public static final List<String> PART_CACHES = List.of(
            PART_DETAIL, PART_PAGE, PART_SEARCH, PART_BY_SUPPLIER);
    public static final List<String> SUPPLIER_CACHES = List.of(
            SUPPLIER_DETAIL, SUPPLIER_PAGE, SUPPLIER_SEARCH);
    public static final List<String> ALL = List.of(
            PART_DETAIL, PART_PAGE, PART_SEARCH, PART_BY_SUPPLIER,
            SUPPLIER_DETAIL, SUPPLIER_PAGE, SUPPLIER_SEARCH);

    private CatalogCacheNames() {
    }
}
