package com.motorparts.cache;

import org.springframework.stereotype.Component;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.StringJoiner;

@Component("catalogCacheKeys")
public class CatalogCacheKeys {

    public String detail(Long id) {
        return segment(id);
    }

    public String partPage(Long current, Long size, String name, String category, Long supplierId) {
        return join(current, size, name, category, supplierId);
    }

    public String supplierPage(Long current, Long size, String name, Integer status, String creditRating) {
        return join(current, size, name, status, creditRating);
    }

    public String search(String keyword) {
        return segment(keyword);
    }

    public String supplierParts(Long supplierId) {
        return segment(supplierId);
    }

    private static String join(Object... values) {
        StringJoiner key = new StringJoiner(":");
        for (Object value : values) {
            key.add(segment(value));
        }
        return key.toString();
    }

    private static String segment(Object value) {
        if (value == null) {
            return "_";
        }
        String normalized = value instanceof String text ? text.trim() : String.valueOf(value);
        if (normalized.isEmpty()) {
            return "_";
        }
        return URLEncoder.encode(normalized, StandardCharsets.UTF_8);
    }
}
