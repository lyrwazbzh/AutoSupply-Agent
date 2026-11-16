package com.motorparts.procurement.receiving;

import com.motorparts.entity.PurchaseOrderWithDetails;

import java.time.LocalDate;
import java.util.List;

public record OrderReceiveResponse(
        Long orderId,
        String orderNumber,
        Integer status,
        LocalDate actualArrivalDate,
        String operationId,
        List<ReceivedLine> receivedLines,
        PurchaseOrderWithDetails order) {

    public record ReceivedLine(
            Long partId,
            Integer receivedQuantity,
            Integer beforeQuantity,
            Integer afterQuantity,
            String warehouseLocation) {
    }
}
