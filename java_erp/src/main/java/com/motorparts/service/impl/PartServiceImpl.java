package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.cache.CatalogCacheInvalidator;
import com.motorparts.cache.CatalogCacheNames;
import com.motorparts.entity.Part;
import com.motorparts.mapper.PartMapper;
import com.motorparts.service.PartService;
import com.motorparts.supplier.quotation.SupplierQuotationService;
import lombok.RequiredArgsConstructor;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 产品/零部件服务实现类
 */
@Service
@RequiredArgsConstructor
public class PartServiceImpl extends ServiceImpl<PartMapper, Part> implements PartService {
    private final CatalogCacheInvalidator cacheInvalidator;
    private final SupplierQuotationService supplierQuotationService;

    @Override
    @Cacheable(cacheNames = CatalogCacheNames.PART_DETAIL,
            key = "@catalogCacheKeys.detail(#id)", unless = "#result == null")
    public Part getPart(Long id) {
        return id == null ? null : baseMapper.selectById(id);
    }

    @Override
    @Transactional
    public boolean createPart(Part part) {
        boolean success = part != null && save(part);
        if (success) {
            supplierQuotationService.syncLegacyDefault(part);
            cacheInvalidator.evictParts();
        }
        return success;
    }

    @Override
    @Transactional
    public boolean updatePart(Part part) {
        boolean success = part != null && part.getId() != null && updateById(part);
        if (success) {
            supplierQuotationService.syncLegacyDefault(baseMapper.selectById(part.getId()));
            cacheInvalidator.evictParts();
        }
        return success;
    }

    @Override
    public boolean deletePart(Long id) {
        boolean success = id != null && removeById(id);
        if (success) cacheInvalidator.evictParts();
        return success;
    }

    @Override
    @Cacheable(cacheNames = CatalogCacheNames.PART_PAGE,
            key = "@catalogCacheKeys.partPage(#current,#size,#name,#category,#supplierId)",
            unless = "#result == null || #result.records.isEmpty()")
    public Page<Part> pageParts(Long current, Long size, String name, String category, Long supplierId) {
        Page<Part> page = new Page<>(current, size);
        LambdaQueryWrapper<Part> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Part::getName, name);
        }

        if (StringUtils.hasText(category)) {
            wrapper.eq(Part::getCategory, category);
        }

        if (supplierId != null) {
            wrapper.and(group -> group.eq(Part::getSupplierId, supplierId)
                    .or().inSql(Part::getId,
                            "SELECT part_id FROM supplier_part WHERE enabled = 1 AND supplier_id = " + supplierId));
        }

        wrapper.orderByDesc(Part::getCreateTime);

        return baseMapper.selectPage(page, wrapper);
    }

    @Override
    @Cacheable(cacheNames = CatalogCacheNames.PART_SEARCH,
            key = "@catalogCacheKeys.search(#name)",
            unless = "#result == null || #result.isEmpty()")
    public List<Part> searchParts(String name) {
        LambdaQueryWrapper<Part> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Part::getName, name);
        }

        wrapper.orderByDesc(Part::getCreateTime);

        return baseMapper.selectList(wrapper);
    }

    @Override
    @Transactional
    public boolean updatePurchasePrice(Long id, BigDecimal purchasePrice) {
        if (id == null || purchasePrice == null || purchasePrice.compareTo(BigDecimal.ZERO) < 0) {
            return false;
        }

        LambdaUpdateWrapper<Part> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Part::getPurchasePrice, purchasePrice)
               .eq(Part::getId, id);

        boolean success = update(wrapper);
        if (success) {
            supplierQuotationService.syncLegacyDefault(baseMapper.selectById(id));
            cacheInvalidator.evictParts();
        }
        return success;
    }

    @Override
    @Cacheable(cacheNames = CatalogCacheNames.PART_BY_SUPPLIER,
            key = "@catalogCacheKeys.supplierParts(#supplierId)",
            unless = "#result == null || #result.isEmpty()")
    public List<Part> getPartsBySupplier(Long supplierId) {
        if (supplierId == null) {
            return List.of();
        }

        return baseMapper.selectBySupplierAssociation(supplierId);
    }

    @Override
    public List<Part> getPartsByIdsOrdered(List<Long> ids) {
        if (ids == null || ids.isEmpty()) return List.of();
        Map<Long, Part> byId = new HashMap<>();
        for (Part part : baseMapper.selectBatchIds(ids)) {
            byId.put(part.getId(), part);
        }
        List<Part> ordered = new ArrayList<>();
        for (Long id : ids) {
            Part part = byId.get(id);
            if (part != null) ordered.add(part);
        }
        return ordered;
    }

    @Override
    public boolean existsPartCode(String partCode, Long excludeId) {
        LambdaQueryWrapper<Part> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Part::getPartCode, partCode);

        if (excludeId != null) {
            wrapper.ne(Part::getId, excludeId);
        }

        return baseMapper.selectCount(wrapper) > 0;
    }
}
