package com.motorparts.common.enums;

import java.util.Map;
import java.util.Set;

/**
 * 供应商状态枚举：1=合作中, 2=已终止, 3=审核中。
 * Harness/MCP 历史注释中的 0=停止 在边界归一为 2。
 */
public enum SupplierStatusEnum {

    COOPERATING(1, "合作中"),
    TERMINATED(2, "已终止"),
    REVIEWING(3, "审核中");

    private final Integer code;
    private final String description;

    /** from → 允许的目标状态 */
    private static final Map<Integer, Set<Integer>> TRANSITIONS = Map.of(
            REVIEWING.code, Set.of(COOPERATING.code, TERMINATED.code),
            COOPERATING.code, Set.of(TERMINATED.code, REVIEWING.code),
            TERMINATED.code, Set.of(REVIEWING.code)
    );

    SupplierStatusEnum(Integer code, String description) {
        this.code = code;
        this.description = description;
    }

    public Integer getCode() {
        return code;
    }

    public String getDescription() {
        return description;
    }

    public static SupplierStatusEnum getByCode(Integer code) {
        Integer normalized = normalize(code);
        for (SupplierStatusEnum status : values()) {
            if (status.getCode().equals(normalized)) {
                return status;
            }
        }
        return null;
    }

    public static boolean isValid(Integer code) {
        return getByCode(code) != null;
    }

    /**
     * null → 1；0 → 2；其余原样。
     */
    public static Integer normalize(Integer code) {
        if (code == null) {
            return COOPERATING.code;
        }
        if (code == 0) {
            return TERMINATED.code;
        }
        return code;
    }

    public static boolean canTransit(Integer from, Integer to) {
        Integer f = normalize(from);
        Integer t = normalize(to);
        if (f.equals(t)) {
            return true;
        }
        Set<Integer> allowed = TRANSITIONS.get(f);
        return allowed != null && allowed.contains(t);
    }
}
