package com.motorparts.replenishment;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ReplenishmentQueryMapper {
    @Select("""
            SELECT p.id AS part_id,
                   COALESCE(i.current_quantity, 0) AS current_quantity,
                   COALESCE(i.safety_stock, p.stock_warning_value, 10) AS safety_stock
            FROM part p
            LEFT JOIN inventory i ON i.part_id = p.id AND i.deleted = 0
            WHERE p.deleted = 0
              AND COALESCE(i.current_quantity, 0) < COALESCE(i.safety_stock, p.stock_warning_value, 10)
            ORDER BY p.id
            """)
    List<LowStockCandidate> selectLowStockCandidates();

    @Select("SELECT COUNT(*) FROM part WHERE deleted=0")
    int countActiveParts();
}
