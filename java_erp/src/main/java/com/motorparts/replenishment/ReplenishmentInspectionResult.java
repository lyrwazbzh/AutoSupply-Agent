package com.motorparts.replenishment;

import java.util.List;

public record ReplenishmentInspectionResult(
        String runNo,
        Integer scannedCount,
        Integer lowStockCount,
        Integer createdCount,
        Integer skippedActiveCount,
        Integer missingSupplierCount,
        List<Long> createdTaskIds) {
}
