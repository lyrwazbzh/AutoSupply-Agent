package com.motorparts.procurement.returnorder;

import com.fasterxml.jackson.annotation.JsonAlias;

public final class PurchaseReturnRequests {
    private PurchaseReturnRequests() {
    }

    public record Create(
            @JsonAlias("purchase_order_id") Long purchaseOrderId,
            @JsonAlias("part_id") Long partId,
            Integer quantity,
            @JsonAlias("reason_type") String reasonType,
            String reason,
            @JsonAlias("operation_id") String operationId) {
    }
}
