package com.motorparts.procurement.returnorder;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

@Mapper
public interface PurchaseReturnMapper extends BaseMapper<PurchaseReturn> {

    @Select("SELECT * FROM purchase_return WHERE id = #{id} FOR UPDATE")
    PurchaseReturn selectByIdForUpdate(@Param("id") Long id);

    @Select("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM purchase_return
            WHERE purchase_order_id = #{orderId}
              AND part_id = #{partId}
              AND status = 'CONFIRMED'
            """)
    int sumConfirmedQuantity(@Param("orderId") Long orderId, @Param("partId") Long partId);

    @Update("""
            UPDATE purchase_return
            SET status = 'CONFIRMED', confirm_operation_id = #{operationId},
                confirmed_by = #{operatorId}, confirmed_at = #{confirmedAt}, update_time = #{confirmedAt}
            WHERE id = #{id} AND status = 'PENDING'
            """)
    int markConfirmed(@Param("id") Long id,
                      @Param("operationId") String operationId,
                      @Param("operatorId") Long operatorId,
                      @Param("confirmedAt") LocalDateTime confirmedAt);
}
