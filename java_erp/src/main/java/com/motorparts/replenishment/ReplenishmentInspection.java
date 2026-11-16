package com.motorparts.replenishment;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

@TableName("replenishment_inspection")
public class ReplenishmentInspection {
    @TableId(type = IdType.AUTO)
    private Long id;
    @TableField("run_no") private String runNo;
    private String source;
    @TableField("started_at") private LocalDateTime startedAt;
    @TableField("completed_at") private LocalDateTime completedAt;
    @TableField("scanned_count") private Integer scannedCount;
    @TableField("low_stock_count") private Integer lowStockCount;
    @TableField("created_count") private Integer createdCount;
    @TableField("skipped_active_count") private Integer skippedActiveCount;
    @TableField("missing_supplier_count") private Integer missingSupplierCount;
    @TableField("create_time") private LocalDateTime createTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getRunNo() { return runNo; }
    public void setRunNo(String runNo) { this.runNo = runNo; }
    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
    public LocalDateTime getStartedAt() { return startedAt; }
    public void setStartedAt(LocalDateTime startedAt) { this.startedAt = startedAt; }
    public LocalDateTime getCompletedAt() { return completedAt; }
    public void setCompletedAt(LocalDateTime completedAt) { this.completedAt = completedAt; }
    public Integer getScannedCount() { return scannedCount; }
    public void setScannedCount(Integer scannedCount) { this.scannedCount = scannedCount; }
    public Integer getLowStockCount() { return lowStockCount; }
    public void setLowStockCount(Integer lowStockCount) { this.lowStockCount = lowStockCount; }
    public Integer getCreatedCount() { return createdCount; }
    public void setCreatedCount(Integer createdCount) { this.createdCount = createdCount; }
    public Integer getSkippedActiveCount() { return skippedActiveCount; }
    public void setSkippedActiveCount(Integer skippedActiveCount) { this.skippedActiveCount = skippedActiveCount; }
    public Integer getMissingSupplierCount() { return missingSupplierCount; }
    public void setMissingSupplierCount(Integer missingSupplierCount) { this.missingSupplierCount = missingSupplierCount; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
