package com.motorparts.procurement.returnorder;

public enum PurchaseReturnReasonType {
    QUANTITY_MISMATCH,
    DAMAGED,
    SPEC_MISMATCH,
    QUALITY_ISSUE,
    OTHER;

    public static PurchaseReturnReasonType parse(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return valueOf(value.trim().toUpperCase());
        } catch (IllegalArgumentException ignored) {
            return null;
        }
    }
}
