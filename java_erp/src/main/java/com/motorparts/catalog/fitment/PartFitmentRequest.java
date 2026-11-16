package com.motorparts.catalog.fitment;

import jakarta.validation.constraints.NotNull;

public record PartFitmentRequest(
        @NotNull(message = "车型ID不能为空") Long vehicleModelId,
        String fitmentNote,
        Boolean verified) {
}
