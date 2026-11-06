package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.LocalMessage;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface LocalMessageMapper extends BaseMapper<LocalMessage> {
}
