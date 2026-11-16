package com.motorparts.supplier.quotation;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@TableName("supplier_part")
public class SupplierPart {
    @TableId(type = IdType.AUTO)
    private Long id;
    @TableField("supplier_id")
    private Long supplierId;
    @TableField("part_id")
    private Long partId;
    @TableField("supplier_part_code")
    private String supplierPartCode;
    @TableField("purchase_price")
    private BigDecimal purchasePrice;
    @TableField("minimum_order_quantity")
    private Integer minimumOrderQuantity;
    @TableField("lead_time_days")
    private Integer leadTimeDays;
    @TableField("quality_rating")
    private BigDecimal qualityRating;
    @TableField("last_purchase_time")
    private LocalDateTime lastPurchaseTime;
    private Boolean enabled;
    @TableField("create_time")
    private LocalDateTime createTime;
    @TableField("update_time")
    private LocalDateTime updateTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getSupplierId() { return supplierId; }
    public void setSupplierId(Long supplierId) { this.supplierId = supplierId; }
    public Long getPartId() { return partId; }
    public void setPartId(Long partId) { this.partId = partId; }
    public String getSupplierPartCode() { return supplierPartCode; }
    public void setSupplierPartCode(String supplierPartCode) { this.supplierPartCode = supplierPartCode; }
    public BigDecimal getPurchasePrice() { return purchasePrice; }
    public void setPurchasePrice(BigDecimal purchasePrice) { this.purchasePrice = purchasePrice; }
    public Integer getMinimumOrderQuantity() { return minimumOrderQuantity; }
    public void setMinimumOrderQuantity(Integer minimumOrderQuantity) { this.minimumOrderQuantity = minimumOrderQuantity; }
    public Integer getLeadTimeDays() { return leadTimeDays; }
    public void setLeadTimeDays(Integer leadTimeDays) { this.leadTimeDays = leadTimeDays; }
    public BigDecimal getQualityRating() { return qualityRating; }
    public void setQualityRating(BigDecimal qualityRating) { this.qualityRating = qualityRating; }
    public LocalDateTime getLastPurchaseTime() { return lastPurchaseTime; }
    public void setLastPurchaseTime(LocalDateTime lastPurchaseTime) { this.lastPurchaseTime = lastPurchaseTime; }
    public Boolean getEnabled() { return enabled; }
    public void setEnabled(Boolean enabled) { this.enabled = enabled; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
