package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.OrderDetail;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 订单明细 Mapper 接口
 */
@Mapper
public interface OrderDetailMapper extends BaseMapper<OrderDetail> {

    /**
     * 物理删除订单明细（绕过 @TableLogic 软删除，直接从数据库删除）
     */
    @Delete("DELETE FROM order_detail WHERE order_id = #{orderId}")
    int physicalDeleteByOrderId(@Param("orderId") Long orderId);

    @Select("SELECT * FROM order_detail WHERE order_id = #{orderId} AND deleted = 0 ORDER BY part_id FOR UPDATE")
    List<OrderDetail> selectByOrderIdForUpdate(@Param("orderId") Long orderId);
}
