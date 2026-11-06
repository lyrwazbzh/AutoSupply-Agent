package com.motorparts.controller;

import com.motorparts.common.Result;
import com.motorparts.service.ErpOperationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@Tag(name = "写操作回查")
@RestController
@RequestMapping("/api/operations")
@RequiredArgsConstructor
public class OperationController {

    private final ErpOperationService erpOperationService;

    @Operation(summary = "按 operationId 回查写操作结果（不重放写请求）")
    @GetMapping("/{operationId}")
    public Result<Map<String, Object>> get(
            @Parameter(description = "网关操作号") @PathVariable String operationId) {
        return erpOperationService.get(operationId);
    }
}
