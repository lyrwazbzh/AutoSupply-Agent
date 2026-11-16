package com.motorparts.replenishment;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonFormat;

import java.time.LocalDate;

public final class ReplenishmentRequests {
    private ReplenishmentRequests() {}

    public record Create(
            @JsonAlias("part_id") Long partId,
            @JsonAlias("suggested_quantity") Integer suggestedQuantity,
            @JsonAlias("preferred_supplier_id") Long preferredSupplierId,
            String reason,
            @JsonAlias("operation_id") String operationId) {
    }

    public record CreateOrder(
            @JsonAlias("supplier_id") Long supplierId,
            Integer quantity,
            @JsonFormat(pattern = "yyyy-MM-dd")
            @JsonAlias("expected_delivery_date") LocalDate expectedDeliveryDate,
            String remark,
            @JsonAlias("operation_id") String operationId) {
    }
}
