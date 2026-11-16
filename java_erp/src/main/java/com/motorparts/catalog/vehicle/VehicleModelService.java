package com.motorparts.catalog.vehicle;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.common.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class VehicleModelService {
    private final VehicleModelMapper mapper;

    @Transactional(readOnly = true)
    public VehicleModel get(Long id) {
        VehicleModel model = id == null ? null : mapper.selectById(id);
        if (model == null) {
            throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "车型不存在");
        }
        return model;
    }

    @Transactional(readOnly = true)
    public List<VehicleModel> search(String keyword, String brand, String series, String model,
                                     Integer year, Integer displacement, int limit) {
        int safeLimit = Math.min(Math.max(limit, 1), 100);
        LambdaQueryWrapper<VehicleModel> query = new LambdaQueryWrapper<>();
        if (StringUtils.hasText(keyword)) {
            String value = keyword.trim();
            query.and(group -> group.like(VehicleModel::getBrand, value)
                    .or().like(VehicleModel::getSeries, value)
                    .or().like(VehicleModel::getModel, value)
                    .or().like(VehicleModel::getEngineCode, value));
        }
        query.eq(StringUtils.hasText(brand), VehicleModel::getBrand, trimToNull(brand))
                .eq(StringUtils.hasText(series), VehicleModel::getSeries, trimToNull(series))
                .eq(StringUtils.hasText(model), VehicleModel::getModel, trimToNull(model))
                .eq(displacement != null, VehicleModel::getDisplacement, displacement);
        if (year != null) {
            query.and(group -> group.isNull(VehicleModel::getModelYearStart)
                    .or().le(VehicleModel::getModelYearStart, year));
            query.and(group -> group.isNull(VehicleModel::getModelYearEnd)
                    .or().ge(VehicleModel::getModelYearEnd, year));
        }
        query.orderByAsc(VehicleModel::getBrand, VehicleModel::getSeries, VehicleModel::getModel,
                        VehicleModel::getModelYearStart)
                .last("LIMIT " + safeLimit);
        return mapper.selectList(query);
    }

    @Transactional
    public VehicleModel create(VehicleModel model) {
        normalizeAndValidate(model);
        if (existsDuplicate(model, null)) {
            throw new BusinessException(ResultCode.DATA_EXISTS, "相同品牌、车型、年款和排量的车型已存在");
        }
        LocalDateTime now = LocalDateTime.now();
        model.setDeleted(0);
        model.setCreateTime(now);
        model.setUpdateTime(now);
        if (mapper.insert(model) != 1) {
            throw new BusinessException("车型创建失败");
        }
        return model;
    }

    @Transactional
    public VehicleModel update(Long id, VehicleModel update) {
        get(id);
        update.setId(id);
        normalizeAndValidate(update);
        if (existsDuplicate(update, id)) {
            throw new BusinessException(ResultCode.DATA_EXISTS, "相同品牌、车型、年款和排量的车型已存在");
        }
        update.setUpdateTime(LocalDateTime.now());
        if (mapper.updateById(update) != 1) {
            throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "车型不存在");
        }
        return mapper.selectById(id);
    }

    private boolean existsDuplicate(VehicleModel model, Long excludeId) {
        LambdaQueryWrapper<VehicleModel> query = new LambdaQueryWrapper<VehicleModel>()
                .eq(VehicleModel::getBrand, model.getBrand())
                .eq(VehicleModel::getModel, model.getModel());
        equalOrNull(query, VehicleModel::getSeries, model.getSeries());
        equalOrNull(query, VehicleModel::getModelYearStart, model.getModelYearStart());
        equalOrNull(query, VehicleModel::getModelYearEnd, model.getModelYearEnd());
        equalOrNull(query, VehicleModel::getDisplacement, model.getDisplacement());
        query.ne(excludeId != null, VehicleModel::getId, excludeId);
        return mapper.selectCount(query) > 0;
    }

    private static <T> void equalOrNull(LambdaQueryWrapper<VehicleModel> query,
                                        com.baomidou.mybatisplus.core.toolkit.support.SFunction<VehicleModel, T> column,
                                        T value) {
        if (value == null) query.isNull(column); else query.eq(column, value);
    }

    private static void normalizeAndValidate(VehicleModel model) {
        if (model == null) throw new IllegalArgumentException("车型不能为空");
        model.setBrand(requiredTrim(model.getBrand(), "品牌不能为空"));
        model.setSeries(trimToNull(model.getSeries()));
        model.setModel(requiredTrim(model.getModel(), "车型不能为空"));
        model.setEngineCode(trimToNull(model.getEngineCode()));
        model.setRemark(trimToNull(model.getRemark()));
        if (model.getModelYearStart() != null && model.getModelYearEnd() != null
                && model.getModelYearStart() > model.getModelYearEnd()) {
            throw new IllegalArgumentException("起始年款不能大于结束年款");
        }
        if (model.getDisplacement() != null && model.getDisplacement() <= 0) {
            throw new IllegalArgumentException("排量必须大于0");
        }
    }

    private static String requiredTrim(String value, String message) {
        String trimmed = trimToNull(value);
        if (trimmed == null) throw new IllegalArgumentException(message);
        return trimmed;
    }
    private static String trimToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }
}
