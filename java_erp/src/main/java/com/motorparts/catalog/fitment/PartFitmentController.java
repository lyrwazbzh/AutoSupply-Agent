package com.motorparts.catalog.fitment;

import com.motorparts.common.Result;
import com.motorparts.entity.Part;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@Tag(name = "零件车型适配")
@RestController
@RequestMapping("/api/parts")
@RequiredArgsConstructor
public class PartFitmentController {
    private final PartFitmentService service;

    @Operation(summary = "查询零件适配的车型")
    @GetMapping("/{partId}/fitments")
    @PreAuthorize("hasAuthority('erp:fitment:read')")
    public Result<List<PartFitmentView>> list(@PathVariable Long partId) {
        return Result.success(service.listForPart(partId));
    }

    @Operation(summary = "新增零件车型适配关系")
    @PostMapping("/{partId}/fitments")
    @PreAuthorize("hasAuthority('erp:fitment:write')")
    public Result<PartFitmentView> add(@PathVariable Long partId,
                                       @Valid @RequestBody PartFitmentRequest request) {
        return Result.success(service.add(partId, request), "车型适配关系创建成功");
    }

    @Operation(summary = "删除零件车型适配关系")
    @DeleteMapping("/{partId}/fitments/{vehicleModelId}")
    @PreAuthorize("hasAuthority('erp:fitment:write')")
    public Result<Void> delete(@PathVariable Long partId, @PathVariable Long vehicleModelId) {
        service.delete(partId, vehicleModelId);
        return Result.success();
    }

    @Operation(summary = "按车型查询适配零件")
    @GetMapping("/search-by-vehicle")
    @PreAuthorize("hasAuthority('erp:fitment:read')")
    public Result<List<Part>> searchByVehicle(@RequestParam Long vehicleModelId) {
        return Result.success(service.searchPartsByVehicle(vehicleModelId));
    }
}
