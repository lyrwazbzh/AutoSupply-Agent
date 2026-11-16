package com.motorparts.catalog.fitment;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

@TableName("part_fitment")
public class PartFitment {
    @TableId(type = IdType.AUTO)
    private Long id;
    @TableField("part_id")
    private Long partId;
    @TableField("vehicle_model_id")
    private Long vehicleModelId;
    @TableField("fitment_note")
    private String fitmentNote;
    private Boolean verified;
    @TableField("create_time")
    private LocalDateTime createTime;
    @TableField("update_time")
    private LocalDateTime updateTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getPartId() { return partId; }
    public void setPartId(Long partId) { this.partId = partId; }
    public Long getVehicleModelId() { return vehicleModelId; }
    public void setVehicleModelId(Long vehicleModelId) { this.vehicleModelId = vehicleModelId; }
    public String getFitmentNote() { return fitmentNote; }
    public void setFitmentNote(String fitmentNote) { this.fitmentNote = fitmentNote; }
    public Boolean getVerified() { return verified; }
    public void setVerified(Boolean verified) { this.verified = verified; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
