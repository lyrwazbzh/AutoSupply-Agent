package com.motorparts.procurement.receiving;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonFormat;

import java.time.LocalDate;

public class OrderReceiveRequest {
    @JsonAlias("operation_id")
    private String operationId;
    @JsonFormat(pattern = "yyyy-MM-dd")
    @JsonAlias({"actual_arrival_date", "actualDeliveryDate"})
    private LocalDate actualArrivalDate;
    @JsonAlias("warehouse_location")
    private String warehouseLocation;
    private String remark;

    public String getOperationId() { return operationId; }
    public void setOperationId(String operationId) { this.operationId = operationId; }
    public LocalDate getActualArrivalDate() { return actualArrivalDate; }
    public void setActualArrivalDate(LocalDate actualArrivalDate) { this.actualArrivalDate = actualArrivalDate; }
    public String getWarehouseLocation() { return warehouseLocation; }
    public void setWarehouseLocation(String warehouseLocation) { this.warehouseLocation = warehouseLocation; }
    public String getRemark() { return remark; }
    public void setRemark(String remark) { this.remark = remark; }
}
