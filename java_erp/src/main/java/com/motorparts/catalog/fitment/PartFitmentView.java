package com.motorparts.catalog.fitment;

import com.motorparts.catalog.vehicle.VehicleModel;

import java.time.LocalDateTime;

public record PartFitmentView(
        Long id,
        Long partId,
        Long vehicleModelId,
        String fitmentNote,
        boolean verified,
        LocalDateTime createTime,
        VehicleModel vehicleModel) {
}
