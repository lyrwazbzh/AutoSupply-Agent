package com.motorparts.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.List;

/**
 * 采购订单（包含订单明细及零部件详情）
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class PurchaseOrderWithDetails extends PurchaseOrder {

    /**
     * 订单明细列表（包含零部件详情）
     */
    private List<OrderDetailWithPart> orderDetail;

    /**
     * 网关操作号（非表字段）
     */
    @JsonAlias({"operation_id"})
    @TableField(exist = false)
    private String operationId;

    /**
     * 幂等命中标记（非表字段）
     */
    @TableField(exist = false)
    private Boolean idempotentReplay;

    /**
     * 操作状态：CONFIRMED / REJECTED / UNKNOWN（非表字段）
     */
    @TableField(exist = false)
    private String operationStatus;

    public List<OrderDetailWithPart> getOrderDetail() {
        return orderDetail;
    }

    public void setOrderDetail(List<OrderDetailWithPart> orderDetail) {
        this.orderDetail = orderDetail;
    }

    public String getOperationId() {
        return operationId;
    }

    public void setOperationId(String operationId) {
        this.operationId = operationId;
    }

    public Boolean getIdempotentReplay() {
        return idempotentReplay;
    }

    public void setIdempotentReplay(Boolean idempotentReplay) {
        this.idempotentReplay = idempotentReplay;
    }

    public String getOperationStatus() {
        return operationStatus;
    }

    public void setOperationStatus(String operationStatus) {
        this.operationStatus = operationStatus;
    }
}
