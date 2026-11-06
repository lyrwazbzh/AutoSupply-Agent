package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.OrderIdempotency;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface OrderIdempotencyMapper extends BaseMapper<OrderIdempotency> {
}
