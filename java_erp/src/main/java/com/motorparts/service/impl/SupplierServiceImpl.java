package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.common.enums.SupplierStatusEnum;
import com.motorparts.entity.Supplier;
import com.motorparts.mapper.SupplierMapper;
import com.motorparts.service.SupplierService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * 供应商服务实现类
 */
@Service
public class SupplierServiceImpl extends ServiceImpl<SupplierMapper, Supplier> implements SupplierService {

    @Override
    public Page<Supplier> pageSuppliers(Page<Supplier> page, String name, Integer status, String creditRating) {
        LambdaQueryWrapper<Supplier> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Supplier::getName, name);
        }

        if (status != null) {
            wrapper.eq(Supplier::getStatus, SupplierStatusEnum.normalize(status));
        }

        if (StringUtils.hasText(creditRating)) {
            wrapper.eq(Supplier::getCreditRating, creditRating);
        }

        wrapper.orderByDesc(Supplier::getCreateTime);

        return baseMapper.selectPage(page, wrapper);
    }

    @Override
    public List<Supplier> searchByName(String name) {
        LambdaQueryWrapper<Supplier> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Supplier::getName, name);
        }

        wrapper.orderByDesc(Supplier::getCreateTime);

        return baseMapper.selectList(wrapper);
    }

    @Override
    public boolean updateStatus(Long id, Integer status) {
        if (id == null || status == null) {
            return false;
        }
        Integer target = SupplierStatusEnum.normalize(status);
        if (!SupplierStatusEnum.isValid(target)) {
            return false;
        }
        Supplier current = getById(id);
        if (current == null || current.getStatus() == null) {
            return false;
        }
        Integer from = SupplierStatusEnum.normalize(current.getStatus());
        if (!SupplierStatusEnum.canTransit(from, target)) {
            return false;
        }
        if (from.equals(target)) {
            return true;
        }
        LambdaUpdateWrapper<Supplier> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Supplier::getStatus, target)
               .eq(Supplier::getId, id)
               .eq(Supplier::getStatus, from);
        return update(wrapper);
    }

    @Override
    public boolean updateCreditRating(Long id, String creditRating) {
        if (id == null || !StringUtils.hasText(creditRating)) {
            return false;
        }

        LambdaUpdateWrapper<Supplier> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Supplier::getCreditRating, creditRating)
               .eq(Supplier::getId, id);

        return update(wrapper);
    }
}