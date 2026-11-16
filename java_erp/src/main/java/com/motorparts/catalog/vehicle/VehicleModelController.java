package com.motorparts.catalog.vehicle;

import com.motorparts.common.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@Tag(name = "摩托车车型档案")
@RestController
@RequestMapping("/api/vehicle-models")
@RequiredArgsConstructor
public class VehicleModelController {
    private final VehicleModelService service;

    @Operation(summary = "搜索车型")
    @GetMapping("/search")
    @PreAuthorize("hasAuthority('erp:vehicle:read')")
    public Result<List<VehicleModel>> search(
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String brand,
            @RequestParam(required = false) String series,
            @RequestParam(required = false) String model,
            @RequestParam(required = false) Integer year,
            @RequestParam(required = false) Integer displacement,
            @RequestParam(defaultValue = "50") int limit) {
        return Result.success(service.search(keyword, brand, series, model, year, displacement, limit));
    }

    @Operation(summary = "获取车型详情")
    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('erp:vehicle:read')")
    public Result<VehicleModel> get(@PathVariable Long id) {
        return Result.success(service.get(id));
    }

    @Operation(summary = "创建车型")
    @PostMapping
    @PreAuthorize("hasAuthority('erp:vehicle:write')")
    public Result<VehicleModel> create(@Valid @RequestBody VehicleModel model) {
        return Result.success(service.create(model), "车型创建成功");
    }

    @Operation(summary = "更新车型")
    @PutMapping("/{id}")
    @PreAuthorize("hasAuthority('erp:vehicle:write')")
    public Result<VehicleModel> update(@PathVariable Long id, @Valid @RequestBody VehicleModel model) {
        return Result.success(service.update(id, model), "车型更新成功");
    }
}
