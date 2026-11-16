package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.Part;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 产品/零部件 Mapper 接口
 */
@Mapper
public interface PartMapper extends BaseMapper<Part> {

    @Select("""
            SELECT DISTINCT p.*
            FROM part p
            WHERE p.deleted = 0
              AND (p.supplier_id = #{supplierId}
                   OR EXISTS (
                       SELECT 1 FROM supplier_part sp
                       WHERE sp.part_id = p.id
                         AND sp.supplier_id = #{supplierId}
                         AND sp.enabled = 1
                   ))
            ORDER BY p.create_time DESC
            """)
    List<Part> selectBySupplierAssociation(@Param("supplierId") Long supplierId);
}
