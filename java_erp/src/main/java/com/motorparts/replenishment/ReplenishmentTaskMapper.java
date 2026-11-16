package com.motorparts.replenishment;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

@Mapper
public interface ReplenishmentTaskMapper extends BaseMapper<ReplenishmentTask> {
    @Select("SELECT * FROM replenishment_task WHERE part_id=#{partId} AND status IN ('PENDING','ORDER_CREATED') LIMIT 1")
    ReplenishmentTask selectActiveByPartId(@Param("partId") Long partId);

    @Select("SELECT * FROM replenishment_task WHERE id=#{id} FOR UPDATE")
    ReplenishmentTask selectByIdForUpdate(@Param("id") Long id);

    @Update("""
            UPDATE replenishment_task
            SET status='ORDER_CREATED', related_order_id=#{orderId}, preferred_supplier_id=#{supplierId},
                suggested_quantity=#{quantity}, update_time=#{updatedAt}
            WHERE id=#{id} AND status='PENDING'
            """)
    int markOrderCreated(@Param("id") Long id, @Param("orderId") Long orderId,
                         @Param("supplierId") Long supplierId, @Param("quantity") Integer quantity,
                         @Param("updatedAt") LocalDateTime updatedAt);

    @Update("""
            UPDATE replenishment_task
            SET status='COMPLETED', completed_at=#{completedAt}, update_time=#{completedAt}
            WHERE id=#{id} AND status='PENDING'
            """)
    int markCompleted(@Param("id") Long id, @Param("completedAt") LocalDateTime completedAt);

    @Update("""
            UPDATE replenishment_task
            SET status='COMPLETED', completed_at=#{completedAt}, update_time=#{completedAt}
            WHERE related_order_id=#{orderId} AND status='ORDER_CREATED'
            """)
    int completeByRelatedOrderId(@Param("orderId") Long orderId,
                                 @Param("completedAt") LocalDateTime completedAt);

    @Update("UPDATE replenishment_task SET status='CANCELLED', update_time=#{updatedAt} WHERE id=#{id} AND status='PENDING'")
    int cancel(@Param("id") Long id, @Param("updatedAt") LocalDateTime updatedAt);
}
