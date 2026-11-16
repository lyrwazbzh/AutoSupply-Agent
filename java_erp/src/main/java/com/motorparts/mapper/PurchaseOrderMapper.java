package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.PurchaseOrder;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDate;

/**
 * 采购订单 Mapper 接口
 */
@Mapper
public interface PurchaseOrderMapper extends BaseMapper<PurchaseOrder> {

    /**
     * 物理删除订单（绕过 @TableLogic 软删除，直接从数据库删除）
     */
    @Delete("DELETE FROM purchase_order WHERE id = #{id}")
    int physicalDeleteById(@Param("id") Long id);

    @Select("SELECT * FROM purchase_order WHERE id = #{id} AND deleted = 0 FOR UPDATE")
    PurchaseOrder selectByIdForUpdate(@Param("id") Long id);

    @Update("""
            UPDATE purchase_order
            SET status = 4, actual_delivery_date = #{actualDeliveryDate}, update_time = NOW()
            WHERE id = #{id} AND deleted = 0 AND status = 3
            """)
    int markReceived(@Param("id") Long id, @Param("actualDeliveryDate") LocalDate actualDeliveryDate);
}
