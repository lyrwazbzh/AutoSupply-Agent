package com.motorparts.inventory.transaction;

import com.motorparts.common.Result;
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
import java.util.List;

@Tag(name = "零件库存流水")
@RestController
@RequestMapping("/api/parts")
@PreAuthorize("hasAuthority('erp:inventory:transaction:read')")
@RequiredArgsConstructor
public class PartInventoryTransactionController {
    private final InventoryTransactionService service;

    @Operation(summary = "查询指定零件的库存流水")
    @GetMapping("/{partId}/inventory-transactions")
    public Result<List<InventoryTransaction>> list(
            @PathVariable Long partId,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime startTime,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime endTime) {
        return Result.success(service.listForPart(partId, startTime, endTime));
    }
}
