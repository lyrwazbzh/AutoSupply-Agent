package com.motorparts.catalog.vehicle;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.motorparts.entity.BaseEntity;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;

@TableName("vehicle_model")
public class VehicleModel extends BaseEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    @NotBlank(message = "品牌不能为空")
    private String brand;
    private String series;
    @NotBlank(message = "车型不能为空")
    private String model;
    @TableField("model_year_start")
    @Min(value = 1885, message = "起始年款不合法")
    private Integer modelYearStart;
    @TableField("model_year_end")
    @Min(value = 1885, message = "结束年款不合法")
    private Integer modelYearEnd;
    @Min(value = 1, message = "排量必须大于0")
    private Integer displacement;
    @TableField("engine_code")
    private String engineCode;
    private String remark;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getBrand() { return brand; }
    public void setBrand(String brand) { this.brand = brand; }
    public String getSeries() { return series; }
    public void setSeries(String series) { this.series = series; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public Integer getModelYearStart() { return modelYearStart; }
    public void setModelYearStart(Integer modelYearStart) { this.modelYearStart = modelYearStart; }
    public Integer getModelYearEnd() { return modelYearEnd; }
    public void setModelYearEnd(Integer modelYearEnd) { this.modelYearEnd = modelYearEnd; }
    public Integer getDisplacement() { return displacement; }
    public void setDisplacement(Integer displacement) { this.displacement = displacement; }
    public String getEngineCode() { return engineCode; }
    public void setEngineCode(String engineCode) { this.engineCode = engineCode; }
    public String getRemark() { return remark; }
    public void setRemark(String remark) { this.remark = remark; }
}
