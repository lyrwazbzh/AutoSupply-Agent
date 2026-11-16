package com.motorparts.supplier.quotation;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.LocalDateTime;

public final class SupplierPartRequests {
    private SupplierPartRequests() {
    }

    public record Create(
            @NotNull(message = "供应商ID不能为空") Long supplierId,
            String supplierPartCode,
            @NotNull(message = "采购价不能为空")
            @DecimalMin(value = "0.00", message = "采购价不能小于0") BigDecimal purchasePrice,
            @Min(value = 1, message = "最小采购量至少为1") Integer minimumOrderQuantity,
            @Min(value = 0, message = "交期不能小于0") Integer leadTimeDays,
            @DecimalMin(value = "0.00", message = "质量评分不能小于0")
            @DecimalMax(value = "5.00", message = "质量评分不能大于5") BigDecimal qualityRating,
            LocalDateTime lastPurchaseTime,
            Boolean enabled,
            Boolean defaultSupplier) {
    }

    public record Update(
            String supplierPartCode,
            @NotNull(message = "采购价不能为空")
            @DecimalMin(value = "0.00", message = "采购价不能小于0") BigDecimal purchasePrice,
            @Min(value = 1, message = "最小采购量至少为1") Integer minimumOrderQuantity,
            @Min(value = 0, message = "交期不能小于0") Integer leadTimeDays,
            @DecimalMin(value = "0.00", message = "质量评分不能小于0")
            @DecimalMax(value = "5.00", message = "质量评分不能大于5") BigDecimal qualityRating,
            LocalDateTime lastPurchaseTime,
            Boolean enabled,
            Boolean defaultSupplier) {
    }
}
