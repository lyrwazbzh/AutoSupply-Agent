package com.motorparts.common;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * 订单幂等业务载荷摘要：剔除网关元数据后 canonical JSON + SHA-256。
 */
public final class PayloadHashUtil {

    private static final Set<String> STRIP_COMPACT = Set.of(
            "operationid",
            "idempotencykey",
            "payloadhash",
            "idempotentreplay",
            "operationstatus",
            "dispatchpayloadhash"
    );

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);

    private PayloadHashUtil() {
    }

    public static String businessPayloadHash(Object payload) {
        try {
            Object converted = MAPPER.convertValue(payload, Object.class);
            Object normalized = normalize(converted);
            String json = MAPPER.writeValueAsString(normalized);
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(json.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder("sha256:");
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException("计算 payloadHash 失败", e);
        }
    }

    private static Object normalize(Object value) {
        if (value instanceof Map<?, ?> map) {
            TreeMap<String, Object> sorted = new TreeMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                String key = String.valueOf(entry.getKey());
                String compact = key.toLowerCase().replace("-", "").replace("_", "");
                if (STRIP_COMPACT.contains(compact)) {
                    continue;
                }
                sorted.put(key, normalize(entry.getValue()));
            }
            return sorted;
        }
        if (value instanceof List<?> list) {
            List<Object> out = new ArrayList<>(list.size());
            for (Object item : list) {
                out.add(normalize(item));
            }
            return out;
        }
        return value;
    }

    public static Map<String, Object> asMutableMap(Object payload) {
        @SuppressWarnings("unchecked")
        Map<String, Object> map = MAPPER.convertValue(payload, LinkedHashMap.class);
        return map == null ? new LinkedHashMap<>() : map;
    }
}
