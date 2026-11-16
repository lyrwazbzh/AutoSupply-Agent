package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.cache.CatalogCacheInvalidator;
import com.motorparts.cache.CatalogCacheNames;
import com.motorparts.common.enums.SupplierStatusEnum;
import com.motorparts.entity.Supplier;
import com.motorparts.mapper.SupplierMapper;
import com.motorparts.service.SupplierService;
import lombok.RequiredArgsConstructor;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 供应商服务实现类
 */
@Service
@RequiredArgsConstructor
public class SupplierServiceImpl extends ServiceImpl<SupplierMapper, Supplier> implements SupplierService {
    private final CatalogCacheInvalidator cacheInvalidator;

    @Override
    @Cacheable(cacheNames = CatalogCacheNames.SUPPLIER_DETAIL,
            key = "@catalogCacheKeys.detail(#id)", unless = "#result == null")
    public Supplier getSupplier(Long id) {
        return id == null ? null : baseMapper.selectById(id);
    }

    @Override
    public boolean createSupplier(Supplier supplier) {
        boolean success = supplier != null && save(supplier);
        if (success) cacheInvalidator.evictSuppliers();
        return success;
    }

    @Override
    public boolean updateSupplier(Supplier supplier) {
        boolean success = supplier != null && supplier.getId() != null && updateById(supplier);
        if (success) cacheInvalidator.evictSuppliers();
        return success;
    }

    @Override
    public boolean deleteSupplier(Long id) {
        boolean success = id != null && removeById(id);
        if (success) cacheInvalidator.evictSuppliers();
        return success;
    }

    @Override
    @Cacheable(cacheNames = CatalogCacheNames.SUPPLIER_PAGE,
            key = "@catalogCacheKeys.supplierPage(#current,#size,#name,#status,#creditRating)",
            unless = "#result == null || #result.records.isEmpty()")
    public Page<Supplier> pageSuppliers(Long current, Long size, String name, Integer status, String creditRating) {
        Page<Supplier> page = new Page<>(current, size);
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
    @Cacheable(cacheNames = CatalogCacheNames.SUPPLIER_SEARCH,
            key = "@catalogCacheKeys.search(#name)",
            unless = "#result == null || #result.isEmpty()")
    public List<Supplier> searchSuppliers(String name) {
        LambdaQueryWrapper<Supplier> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Supplier::getName, name);
        }

        wrapper.orderByDesc(Supplier::getCreateTime);

        return baseMapper.selectList(wrapper);
    }

    @Override
    public List<Supplier> getSuppliersByIdsOrdered(List<Long> ids) {
        if (ids == null || ids.isEmpty()) return List.of();
        Map<Long, Supplier> byId = new HashMap<>();
        for (Supplier supplier : baseMapper.selectBatchIds(ids)) {
            byId.put(supplier.getId(), supplier);
        }
        List<Supplier> ordered = new ArrayList<>();
        for (Long id : ids) {
            Supplier supplier = byId.get(id);
            if (supplier != null) ordered.add(supplier);
        }
        return ordered;
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
        Supplier current = baseMapper.selectById(id);
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
        boolean success = update(wrapper);
        if (success) cacheInvalidator.evictSuppliers();
        return success;
    }

    @Override
    public boolean updateCreditRating(Long id, String creditRating) {
        if (id == null || !StringUtils.hasText(creditRating)) {
            return false;
        }

        LambdaUpdateWrapper<Supplier> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Supplier::getCreditRating, creditRating)
               .eq(Supplier::getId, id);

        boolean success = update(wrapper);
        if (success) cacheInvalidator.evictSuppliers();
        return success;
    }
}
