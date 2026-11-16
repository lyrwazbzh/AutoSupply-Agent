package com.motorparts.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.OperationIds;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.entity.Part;
import com.motorparts.redis.ActivityService;
import com.motorparts.service.ErpOperationService;
import com.motorparts.service.PartService;
import io.swagger.v3.oas.annotations.tags.Tag;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;

import jakarta.validation.Valid;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 产品/零部件管理控制器
 */
@Tag(name = "产品/零部件管理")
@RestController
@RequestMapping("/api/parts")
@PreAuthorize("hasAuthority('erp:part:read')")
@RequiredArgsConstructor
@Validated
public class PartController {

    private final PartService partService;
    private final ErpOperationService erpOperationService;
    private final ActivityService activityService;

    /**
     * 创建零部件
     */
    @Operation(summary = "创建零部件")
    @PostMapping("/create")
    @PreAuthorize("hasAuthority('erp:part:write')")
    public Result<?> create(
            @Valid @RequestBody Part part,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader) {
        String opId = OperationIds.resolve(null, operationId, operationHeader);
        Result<?> replay = erpOperationService.replay(opId);
        if (replay != null) {
            return replay;
        }
        if (partService.existsPartCode(part.getPartCode(), null)) {
            return Result.error(ResultCode.DATA_EXISTS);
        }
        part.setDeleted(0);
        part.setCreateTime(LocalDateTime.now());
        part.setUpdateTime(LocalDateTime.now());
        boolean success = partService.createPart(part);
        if (!success) {
            return Result.error();
        }
        Result<?> result = Result.success(part, "创建成功");
        erpOperationService.complete(opId, result);
        return result;
    }

    /**
     * 更新零部件
     */
    @Operation(summary = "更新零部件")
    @PutMapping("/update/{id}")
    @PreAuthorize("hasAuthority('erp:part:write')")
    public Result<Part> update(
            @Parameter(description = "零部件ID") @PathVariable Long id,
            @Valid @RequestBody Part part) {
        part.setId(id);
        // 检查零件编码是否已存在
        if (partService.existsPartCode(part.getPartCode(), id)) {
            return Result.error(ResultCode.DATA_EXISTS);
        }
        // 手动设置updateTime字段
        part.setUpdateTime(LocalDateTime.now());
        boolean success = partService.updatePart(part);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(part);
    }

    /**
     * 删除零部件（逻辑删除）
     */
    @Operation(summary = "删除零部件")
    @DeleteMapping("/delete/{id}")
    @PreAuthorize("hasAuthority('erp:part:write')")
    public Result<Void> delete(@Parameter(description = "零部件ID") @PathVariable Long id) {
        boolean success = partService.deletePart(id);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取单个零部件
     */
    @Operation(summary = "获取单个零部件")
    @GetMapping("/get/{id}")
    public Result<Part> getById(@Parameter(description = "零部件ID") @PathVariable Long id,
                                JwtAuthenticationToken authentication) {
        Part part = partService.getPart(id);
        if (part == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        activityService.recordPart(authentication.getToken().getSubject(), id);
        return Result.success(part);
    }

    /**
     * 分页查询零部件
     */
    @Operation(summary = "分页查询零部件")
    @GetMapping("/page")
    public Result<PageResult<Part>> page(
            @Parameter(description = "当前页码") @RequestParam(defaultValue = "1") Long current,
            @Parameter(description = "每页大小") @RequestParam(defaultValue = "10") Long size,
            @Parameter(description = "零件名称") @RequestParam(required = false) String name,
            @Parameter(description = "分类") @RequestParam(required = false) String category,
            @Parameter(description = "供应商ID") @RequestParam(required = false) Long supplierId) {
        Page<Part> result = partService.pageParts(current, size, name, category, supplierId);
        return Result.success(PageResult.from(result));
    }

    /**
     * 搜索零部件
     */
    @Operation(summary = "搜索零部件")
    @GetMapping("/search")
    public Result<List<Part>> search(
            @Parameter(description = "零件名称关键字") @RequestParam String name) {
        List<Part> list = partService.searchParts(name);
        return Result.success(list);
    }

    /**
     * 更新采购单价
     */
    @Operation(summary = "更新采购单价")
    @PatchMapping("/update-price/{id}")
    @PreAuthorize("hasAuthority('erp:part:price')")
    public Result<Void> updatePrice(
            @Parameter(description = "零部件ID") @PathVariable Long id,
            @Parameter(description = "新采购单价") @RequestParam BigDecimal purchasePrice) {
        boolean success = partService.updatePurchasePrice(id, purchasePrice);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取供应商的产品列表
     */
    @Operation(summary = "获取供应商的产品列表")
    @GetMapping("/supplier/{supplierId}")
    public Result<List<Part>> getBySupplierId(
            @Parameter(description = "供应商ID") @PathVariable Long supplierId) {
        List<Part> list = partService.getPartsBySupplier(supplierId);
        return Result.success(list);
    }

    @Operation(summary = "最近访问的零部件")
    @GetMapping("/recent")
    public Result<List<Part>> recent(
            @RequestParam(defaultValue = "10") int limit,
            JwtAuthenticationToken authentication) {
        List<Long> ids = activityService.recentParts(authentication.getToken().getSubject(), limit);
        return Result.success(partService.getPartsByIdsOrdered(ids));
    }

    @Operation(summary = "常用零部件")
    @GetMapping("/frequent")
    public Result<List<Part>> frequent(
            @RequestParam(defaultValue = "10") int limit,
            JwtAuthenticationToken authentication) {
        List<Long> ids = activityService.frequentParts(authentication.getToken().getSubject(), limit);
        return Result.success(partService.getPartsByIdsOrdered(ids));
    }
}
