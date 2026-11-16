package com.motorparts.replenishment;

import com.motorparts.entity.PurchaseOrderWithDetails;

public record ReplenishmentOrderResult(
        ReplenishmentTask task,
        PurchaseOrderWithDetails order) {
}
