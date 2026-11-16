package com.motorparts.inventory.transaction;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;

@Tag(name = "库存流水")
@RestController
@RequestMapping("/api/inventory/transactions")
@PreAuthorize("hasAuthority('erp:inventory:transaction:read')")
@RequiredArgsConstructor
public class InventoryTransactionController {
    private final InventoryTransactionService service;

    @Operation(summary = "分页查询库存流水")
    @GetMapping("/page")
    public Result<PageResult<InventoryTransaction>> page(
            @RequestParam(defaultValue = "1") long current,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) Long partId,
            @RequestParam(required = false) String transactionType,
            @RequestParam(required = false) String sourceType,
            @RequestParam(required = false) Long sourceId,
            @RequestParam(required = false) Long operatorId,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime startTime,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime endTime,
            @RequestParam(required = false) String operationId) {
        Page<InventoryTransaction> result = service.page(current, size, partId, transactionType,
                sourceType, sourceId, operatorId, startTime, endTime, operationId);
        return Result.success(PageResult.from(result));
    }

    @Operation(summary = "获取库存流水详情")
    @GetMapping("/{id}")
    public Result<InventoryTransaction> get(@PathVariable Long id) {
        InventoryTransaction row = service.get(id);
        return row == null ? Result.error(ResultCode.DATA_NOT_EXISTS) : Result.success(row);
    }
}
