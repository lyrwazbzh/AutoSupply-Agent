package com.motorparts.supplier.quotation;

import java.math.BigDecimal;
import java.time.LocalDateTime;

public record SupplierOptionView(
        Long id,
        Long partId,
        Long supplierId,
        String supplierCode,
        String supplierName,
        Integer supplierStatus,
        String supplierPartCode,
        BigDecimal purchasePrice,
        Integer minimumOrderQuantity,
        Integer leadTimeDays,
        BigDecimal qualityRating,
        LocalDateTime lastPurchaseTime,
        boolean enabled,
        boolean defaultSupplier) {
}
