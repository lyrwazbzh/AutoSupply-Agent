package com.motorparts.supplier.quotation;

import com.motorparts.common.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@Tag(name = "零件供应商报价")
@RestController
@RequestMapping("/api/parts/{partId}/supplier-options")
@RequiredArgsConstructor
public class SupplierQuotationController {
    private final SupplierQuotationService service;

    @Operation(summary = "查询零件的所有供应商报价")
    @GetMapping
    @PreAuthorize("hasAuthority('erp:supplier-part:read')")
    public Result<List<SupplierOptionView>> list(@PathVariable Long partId) {
        return Result.success(service.listOptions(partId));
    }

    @Operation(summary = "为零件新增供应商报价")
    @PostMapping
    @PreAuthorize("hasAuthority('erp:supplier-part:write')")
    public Result<SupplierOptionView> create(@PathVariable Long partId,
                                             @Valid @RequestBody SupplierPartRequests.Create request) {
        return Result.success(service.create(partId, request), "供应商报价创建成功");
    }

    @Operation(summary = "更新零件的供应商报价")
    @PutMapping("/{supplierId}")
    @PreAuthorize("hasAuthority('erp:supplier-part:write')")
    public Result<SupplierOptionView> update(@PathVariable Long partId,
                                             @PathVariable Long supplierId,
                                             @Valid @RequestBody SupplierPartRequests.Update request) {
        return Result.success(service.update(partId, supplierId, request), "供应商报价更新成功");
    }

    @Operation(summary = "删除非默认供应商报价")
    @DeleteMapping("/{supplierId}")
    @PreAuthorize("hasAuthority('erp:supplier-part:write')")
    public Result<Void> delete(@PathVariable Long partId, @PathVariable Long supplierId) {
        service.delete(partId, supplierId);
        return Result.success();
    }
}
