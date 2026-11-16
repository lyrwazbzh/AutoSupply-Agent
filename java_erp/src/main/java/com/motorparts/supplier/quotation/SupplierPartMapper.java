package com.motorparts.supplier.quotation;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

@Mapper
public interface SupplierPartMapper extends BaseMapper<SupplierPart> {
    @Update("""
            UPDATE supplier_part sp
            JOIN part p ON p.id = sp.part_id AND p.supplier_id = sp.supplier_id
            SET sp.last_purchase_time = #{purchasedAt}, sp.update_time = #{purchasedAt}
            WHERE sp.part_id = #{partId}
            """)
    int touchDefaultSupplierPurchase(@Param("partId") Long partId,
                                     @Param("purchasedAt") LocalDateTime purchasedAt);

    @Update("""
            UPDATE supplier_part
            SET last_purchase_time = #{purchasedAt}, update_time = #{purchasedAt}
            WHERE part_id = #{partId} AND supplier_id = #{supplierId}
            """)
    int touchSupplierPurchase(@Param("partId") Long partId,
                              @Param("supplierId") Long supplierId,
                              @Param("purchasedAt") LocalDateTime purchasedAt);
}
