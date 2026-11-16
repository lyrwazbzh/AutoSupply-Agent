package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.Inventory;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

/**
 * 库存 Mapper 接口
 */
@Mapper
public interface InventoryMapper extends BaseMapper<Inventory> {

    @Select("SELECT COUNT(*) FROM inventory WHERE deleted = 0 AND current_quantity <= safety_stock")
    long countWarnings();

    @Insert("""
            INSERT INTO inventory(part_id, current_quantity, safety_stock, warehouse_location, deleted, create_time, update_time)
            VALUES(#{partId}, 0, 10, #{warehouseLocation}, 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE id = id
            """)
    int insertEmptyIfAbsent(@Param("partId") Long partId,
                            @Param("warehouseLocation") String warehouseLocation);

    @Select("""
            SELECT id, part_id, current_quantity, safety_stock, last_inbound_time, last_outbound_time,
                   warehouse_location, deleted, create_time, update_time
            FROM inventory
            WHERE part_id = #{partId} AND deleted = 0
            FOR UPDATE
            """)
    Inventory selectByPartIdForUpdate(@Param("partId") Long partId);

    @Update("""
            <script>
            UPDATE inventory
            SET current_quantity = #{afterQuantity},
                last_inbound_time = #{occurredAt},
                update_time = #{occurredAt}
                <if test="warehouseLocation != null and warehouseLocation != ''">
                  , warehouse_location = #{warehouseLocation}
                </if>
            WHERE id = #{id} AND deleted = 0
            </script>
            """)
    int applyInbound(@Param("id") Long id,
                     @Param("afterQuantity") Integer afterQuantity,
                     @Param("warehouseLocation") String warehouseLocation,
                     @Param("occurredAt") LocalDateTime occurredAt);

    @Update("""
            UPDATE inventory
            SET current_quantity = #{afterQuantity}, last_outbound_time = #{occurredAt}, update_time = #{occurredAt}
            WHERE id = #{id} AND deleted = 0 AND current_quantity >= #{quantity}
            """)
    int applyOutbound(@Param("id") Long id,
                      @Param("quantity") Integer quantity,
                      @Param("afterQuantity") Integer afterQuantity,
                      @Param("occurredAt") LocalDateTime occurredAt);

}
