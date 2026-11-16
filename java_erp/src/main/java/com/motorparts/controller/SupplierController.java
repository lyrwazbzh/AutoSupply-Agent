package com.motorparts.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.OperationIds;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.common.enums.SupplierStatusEnum;
import com.motorparts.entity.Supplier;
import com.motorparts.redis.ActivityService;
import com.motorparts.service.ErpOperationService;
import com.motorparts.service.SupplierService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;

import jakarta.validation.Valid;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 供应商管理控制器
 */
@Tag(name = "供应商管理")
@RestController
@RequestMapping("/api/suppliers")
@PreAuthorize("hasAuthority('erp:supplier:read')")
@RequiredArgsConstructor
@Validated
public class SupplierController {

    private final SupplierService supplierService;
    private final ErpOperationService erpOperationService;
    private final ActivityService activityService;

    /**
     * 创建供应商
     */
    @Operation(summary = "创建供应商")
    @PostMapping("/create")
    @PreAuthorize("hasAuthority('erp:supplier:write')")
    public Result<?> create(
            @Valid @RequestBody Supplier supplier,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader) {
        String opId = OperationIds.resolve(null, operationId, operationHeader);
        Result<?> replay = erpOperationService.replay(opId);
        if (replay != null) {
            return replay;
        }
        Integer normalized = SupplierStatusEnum.normalize(supplier.getStatus());
        if (!SupplierStatusEnum.isValid(normalized)) {
            return Result.error(ResultCode.SUPPLIER_STATUS_ERROR);
        }
        supplier.setStatus(normalized);
        supplier.setDeleted(0);
        supplier.setCreateTime(LocalDateTime.now());
        supplier.setUpdateTime(LocalDateTime.now());
        boolean success = supplierService.createSupplier(supplier);
        if (!success) {
            return Result.error(ResultCode.DATA_EXISTS);
        }
        Result<?> result = Result.success(supplier, "创建成功");
        erpOperationService.complete(opId, result);
        return result;
    }

    /**
     * 更新供应商
     */
    @Operation(summary = "更新供应商")
    @PutMapping("/update/{id}")
    @PreAuthorize("hasAuthority('erp:supplier:write')")
    public Result<Supplier> update(
            @Parameter(description = "供应商ID") @PathVariable Long id,
            @Valid @RequestBody Supplier supplier) {
        supplier.setId(id);
        if (supplier.getStatus() != null) {
            Integer normalized = SupplierStatusEnum.normalize(supplier.getStatus());
            if (!SupplierStatusEnum.isValid(normalized)) {
                return Result.error(ResultCode.SUPPLIER_STATUS_ERROR);
            }
            supplier.setStatus(normalized);
        }
        supplier.setUpdateTime(LocalDateTime.now());
        boolean success = supplierService.updateSupplier(supplier);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(supplier);
    }

    /**
     * 删除供应商（逻辑删除）
     */
    @Operation(summary = "删除供应商")
    @DeleteMapping("/delete/{id}")
    @PreAuthorize("hasAuthority('erp:supplier:write')")
    public Result<Void> delete(@Parameter(description = "供应商ID") @PathVariable Long id) {
        boolean success = supplierService.deleteSupplier(id);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取单个供应商
     */
    @Operation(summary = "获取单个供应商")
    @GetMapping("/get/{id}")
    public Result<Supplier> getById(@Parameter(description = "供应商ID") @PathVariable Long id,
                                    JwtAuthenticationToken authentication) {
        Supplier supplier = supplierService.getSupplier(id);
        if (supplier == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        activityService.recordSupplier(authentication.getToken().getSubject(), id);
        return Result.success(supplier);
    }

    /**
     * 分页查询供应商
     */
    @Operation(summary = "分页查询供应商")
    @GetMapping("/page")
    public Result<PageResult<Supplier>> page(
            @Parameter(description = "当前页码") @RequestParam(defaultValue = "1") Long current,
            @Parameter(description = "每页大小") @RequestParam(defaultValue = "10") Long size,
            @Parameter(description = "供应商名称") @RequestParam(required = false) String name,
            @Parameter(description = "合作状态") @RequestParam(required = false) Integer status,
            @Parameter(description = "信用评级") @RequestParam(required = false) String creditRating) {
        Page<Supplier> result = supplierService.pageSuppliers(current, size, name, status, creditRating);
        return Result.success(PageResult.from(result));
    }

    /**
     * 搜索供应商
     */
    @Operation(summary = "搜索供应商")
    @GetMapping("/search")
    public Result<List<Supplier>> search(
            @Parameter(description = "供应商名称关键字") @RequestParam String name) {
        List<Supplier> list = supplierService.searchSuppliers(name);
        return Result.success(list);
    }

    /**
     * 更新供应商状态
     */
    @Operation(summary = "更新供应商状态")
    @PatchMapping("/update-status/{id}")
    @PreAuthorize("hasAuthority('erp:supplier:status')")
    public Result<?> updateStatus(
            @Parameter(description = "供应商ID") @PathVariable Long id,
            @Parameter(description = "新状态") @RequestParam Integer status,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader) {
        String opId = OperationIds.resolve(null, operationId, operationHeader);
        Result<?> replay = erpOperationService.replay(opId);
        if (replay != null) {
            return replay;
        }
        if (supplierService.getSupplier(id) == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        boolean success = supplierService.updateStatus(id, status);
        if (!success) {
            return Result.error(ResultCode.SUPPLIER_STATUS_ERROR);
        }
        Supplier supplier = supplierService.getSupplier(id);
        Result<?> result = Result.success(supplier, "状态更新成功");
        erpOperationService.complete(opId, result);
        return result;
    }

    /**
     * 更新信用评级
     */
    @Operation(summary = "更新信用评级")
    @PatchMapping("/update-credit-rating/{id}")
    @PreAuthorize("hasAuthority('erp:supplier:write')")
    public Result<Void> updateCreditRating(
            @Parameter(description = "供应商ID") @PathVariable Long id,
            @Parameter(description = "新信用评级") @RequestParam String creditRating) {
        boolean success = supplierService.updateCreditRating(id, creditRating);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    @Operation(summary = "最近访问的供应商")
    @GetMapping("/recent")
    public Result<List<Supplier>> recent(
            @RequestParam(defaultValue = "10") int limit,
            JwtAuthenticationToken authentication) {
        List<Long> ids = activityService.recentSuppliers(authentication.getToken().getSubject(), limit);
        return Result.success(supplierService.getSuppliersByIdsOrdered(ids));
    }

    @Operation(summary = "常用供应商")
    @GetMapping("/frequent")
    public Result<List<Supplier>> frequent(
            @RequestParam(defaultValue = "10") int limit,
            JwtAuthenticationToken authentication) {
        List<Long> ids = activityService.frequentSuppliers(authentication.getToken().getSubject(), limit);
        return Result.success(supplierService.getSuppliersByIdsOrdered(ids));
    }
}
