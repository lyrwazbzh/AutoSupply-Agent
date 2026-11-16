package com.motorparts.supplier.quotation;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.motorparts.cache.CatalogCacheInvalidator;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.common.exception.BusinessException;
import com.motorparts.entity.Part;
import com.motorparts.entity.Supplier;
import com.motorparts.mapper.PartMapper;
import com.motorparts.mapper.SupplierMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class SupplierQuotationService {
    private final SupplierPartMapper supplierPartMapper;
    private final PartMapper partMapper;
    private final SupplierMapper supplierMapper;
    private final CatalogCacheInvalidator cacheInvalidator;

    @Transactional(readOnly = true)
    public List<SupplierOptionView> listOptions(Long partId) {
        Part part = requirePart(partId);
        List<SupplierPart> relations = supplierPartMapper.selectList(new LambdaQueryWrapper<SupplierPart>()
                .eq(SupplierPart::getPartId, partId));
        if (relations.isEmpty()) {
            return List.of();
        }
        Map<Long, Supplier> suppliers = new HashMap<>();
        for (Supplier supplier : supplierMapper.selectBatchIds(
                relations.stream().map(SupplierPart::getSupplierId).distinct().toList())) {
            suppliers.put(supplier.getId(), supplier);
        }
        Comparator<SupplierOptionView> order = Comparator
                .comparing(SupplierOptionView::enabled).reversed()
                .thenComparing(SupplierOptionView::defaultSupplier, Comparator.reverseOrder())
                .thenComparing(SupplierOptionView::purchasePrice, Comparator.nullsLast(Comparator.naturalOrder()))
                .thenComparing(SupplierOptionView::leadTimeDays, Comparator.nullsLast(Comparator.naturalOrder()))
                .thenComparing(SupplierOptionView::qualityRating, Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(SupplierOptionView::supplierName, Comparator.nullsLast(String::compareToIgnoreCase));
        return relations.stream()
                .filter(relation -> suppliers.containsKey(relation.getSupplierId()))
                .map(relation -> toView(relation, suppliers.get(relation.getSupplierId()), part.getSupplierId()))
                .sorted(order)
                .toList();
    }

    @Transactional
    public SupplierOptionView create(Long partId, SupplierPartRequests.Create request) {
        Part part = requirePart(partId);
        Supplier supplier = requireSupplier(request.supplierId());
        boolean targetEnabled = enabled(request.enabled());
        assertSupplierCanBeEnabled(supplier, targetEnabled);
        assertDefaultCanBeUsed(Boolean.TRUE.equals(request.defaultSupplier()), targetEnabled);
        if (find(partId, request.supplierId()) != null) {
            throw new BusinessException(ResultCode.DATA_EXISTS, "该零件与供应商的报价关系已存在");
        }
        SupplierPart relation = new SupplierPart();
        relation.setPartId(partId);
        relation.setSupplierId(request.supplierId());
        apply(relation, request.supplierPartCode(), request.purchasePrice(), request.minimumOrderQuantity(),
                request.leadTimeDays(), request.qualityRating(), request.lastPurchaseTime(), request.enabled());
        LocalDateTime now = LocalDateTime.now();
        relation.setCreateTime(now);
        relation.setUpdateTime(now);
        try {
            if (supplierPartMapper.insert(relation) != 1) {
                throw new BusinessException("供应商报价保存失败");
            }
        } catch (DuplicateKeyException duplicate) {
            throw new BusinessException(ResultCode.DATA_EXISTS, "该零件与供应商的报价关系已存在");
        }
        if (Boolean.TRUE.equals(request.defaultSupplier())) {
            makeDefault(part, relation);
        }
        cacheInvalidator.evictParts();
        return toView(relation, supplier, Boolean.TRUE.equals(request.defaultSupplier())
                ? relation.getSupplierId() : part.getSupplierId());
    }

    @Transactional
    public SupplierOptionView update(Long partId, Long supplierId, SupplierPartRequests.Update request) {
        Part part = requirePart(partId);
        Supplier supplier = requireSupplier(supplierId);
        SupplierPart relation = requireRelation(partId, supplierId);
        boolean targetEnabled = enabled(request.enabled());
        assertSupplierCanBeEnabled(supplier, targetEnabled);
        assertDefaultCanBeUsed(Boolean.TRUE.equals(request.defaultSupplier()), targetEnabled);
        if (!targetEnabled && supplierId.equals(part.getSupplierId())) {
            throw new BusinessException(ResultCode.BUSINESS_ERROR,
                    "默认供应商报价不能停用，请先将其他报价设为默认供应商");
        }
        apply(relation, request.supplierPartCode(), request.purchasePrice(), request.minimumOrderQuantity(),
                request.leadTimeDays(), request.qualityRating(), request.lastPurchaseTime(), request.enabled());
        relation.setUpdateTime(LocalDateTime.now());
        if (supplierPartMapper.updateById(relation) != 1) {
            throw new BusinessException("供应商报价更新失败");
        }
        if (Boolean.TRUE.equals(request.defaultSupplier())) {
            makeDefault(part, relation);
        }
        cacheInvalidator.evictParts();
        return toView(relation, supplier, Boolean.TRUE.equals(request.defaultSupplier())
                ? relation.getSupplierId() : part.getSupplierId());
    }

    @Transactional
    public void delete(Long partId, Long supplierId) {
        Part part = requirePart(partId);
        SupplierPart relation = requireRelation(partId, supplierId);
        if (supplierId.equals(part.getSupplierId())) {
            throw new BusinessException(ResultCode.BUSINESS_ERROR,
                    "默认供应商关系不能删除，请先将其他报价设为默认供应商");
        }
        if (supplierPartMapper.deleteById(relation.getId()) != 1) {
            throw new BusinessException("供应商报价删除失败");
        }
        cacheInvalidator.evictParts();
    }

    /** Keep the legacy default-supplier field and the new relation table consistent. */
    @Transactional
    public void syncLegacyDefault(Part part) {
        if (part == null || part.getId() == null || part.getSupplierId() == null) {
            return;
        }
        SupplierPart relation = find(part.getId(), part.getSupplierId());
        if (relation == null) {
            relation = new SupplierPart();
            relation.setPartId(part.getId());
            relation.setSupplierId(part.getSupplierId());
            relation.setSupplierPartCode(part.getPartCode());
            relation.setPurchasePrice(zeroIfNull(part.getPurchasePrice()));
            relation.setMinimumOrderQuantity(1);
            relation.setEnabled(true);
            LocalDateTime now = LocalDateTime.now();
            relation.setCreateTime(now);
            relation.setUpdateTime(now);
            supplierPartMapper.insert(relation);
        } else if (part.getPurchasePrice() != null
                && (relation.getPurchasePrice() == null
                    || part.getPurchasePrice().compareTo(relation.getPurchasePrice()) != 0)) {
            relation.setPurchasePrice(part.getPurchasePrice());
            relation.setUpdateTime(LocalDateTime.now());
            supplierPartMapper.updateById(relation);
        }
    }

    private void makeDefault(Part part, SupplierPart relation) {
        Part compatibilityUpdate = new Part();
        compatibilityUpdate.setId(part.getId());
        compatibilityUpdate.setSupplierId(relation.getSupplierId());
        compatibilityUpdate.setPurchasePrice(relation.getPurchasePrice());
        compatibilityUpdate.setUpdateTime(LocalDateTime.now());
        int changed = partMapper.updateById(compatibilityUpdate);
        if (changed != 1) {
            throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "零件不存在或默认供应商更新失败");
        }
        part.setSupplierId(relation.getSupplierId());
        part.setPurchasePrice(relation.getPurchasePrice());
    }

    private void apply(SupplierPart relation, String supplierPartCode, BigDecimal price, Integer minimumOrderQuantity,
                       Integer leadTimeDays, BigDecimal qualityRating, LocalDateTime lastPurchaseTime, Boolean enabled) {
        relation.setSupplierPartCode(trimToNull(supplierPartCode));
        relation.setPurchasePrice(price);
        relation.setMinimumOrderQuantity(minimumOrderQuantity == null ? 1 : minimumOrderQuantity);
        relation.setLeadTimeDays(leadTimeDays);
        relation.setQualityRating(qualityRating);
        relation.setLastPurchaseTime(lastPurchaseTime);
        relation.setEnabled(enabled(enabled));
    }

    private SupplierPart find(Long partId, Long supplierId) {
        return supplierPartMapper.selectOne(new LambdaQueryWrapper<SupplierPart>()
                .eq(SupplierPart::getPartId, partId)
                .eq(SupplierPart::getSupplierId, supplierId));
    }

    private SupplierPart requireRelation(Long partId, Long supplierId) {
        SupplierPart relation = find(partId, supplierId);
        if (relation == null) {
            throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "供应商报价关系不存在");
        }
        return relation;
    }

    private Part requirePart(Long partId) {
        Part part = partId == null ? null : partMapper.selectById(partId);
        if (part == null) {
            throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "零件不存在");
        }
        return part;
    }

    private Supplier requireSupplier(Long supplierId) {
        Supplier supplier = supplierId == null ? null : supplierMapper.selectById(supplierId);
        if (supplier == null) {
            throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "供应商不存在");
        }
        return supplier;
    }

    private static void assertSupplierCanBeEnabled(Supplier supplier, boolean enabled) {
        if (enabled && !Integer.valueOf(1).equals(supplier.getStatus())) {
            throw new BusinessException(ResultCode.SUPPLIER_STATUS_ERROR, "只有合作中的供应商才能启用报价");
        }
    }

    private static void assertDefaultCanBeUsed(boolean makeDefault, boolean enabled) {
        if (makeDefault && !enabled) {
            throw new BusinessException(ResultCode.BUSINESS_ERROR, "停用的供应商报价不能设为默认供应商");
        }
    }

    private static SupplierOptionView toView(SupplierPart relation, Supplier supplier, Long defaultSupplierId) {
        return new SupplierOptionView(relation.getId(), relation.getPartId(), relation.getSupplierId(),
                supplier.getSupplierCode(), supplier.getName(), supplier.getStatus(), relation.getSupplierPartCode(),
                relation.getPurchasePrice(), relation.getMinimumOrderQuantity(), relation.getLeadTimeDays(),
                relation.getQualityRating(), relation.getLastPurchaseTime(),
                enabled(relation.getEnabled()) && Integer.valueOf(1).equals(supplier.getStatus()),
                relation.getSupplierId().equals(defaultSupplierId));
    }

    private static boolean enabled(Boolean value) { return value == null || value; }
    private static String trimToNull(String value) {
        if (value == null || value.isBlank()) return null;
        return value.trim();
    }
    private static BigDecimal zeroIfNull(BigDecimal value) { return value == null ? BigDecimal.ZERO : value; }
}
