package com.motorparts.replenishment;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.OperationIds;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "补货任务")
@RestController
@RequestMapping("/api/replenishment")
@PreAuthorize("hasAuthority('erp:replenishment:read')")
@RequiredArgsConstructor
public class ReplenishmentController {
    private final ReplenishmentService service;

    @Operation(summary = "分页查询补货任务")
    @GetMapping("/page")
    public Result<PageResult<ReplenishmentTask>> page(
            @RequestParam(defaultValue = "1") long current,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) Long partId,
            @RequestParam(required = false) String source) {
        Page<ReplenishmentTask> page = service.page(current, size, status, partId, source);
        return Result.success(PageResult.from(page));
    }

    @Operation(summary = "人工创建补货任务")
    @PostMapping("/create")
    @PreAuthorize("hasAuthority('erp:replenishment:manage')")
    public Result<?> create(
            @RequestBody ReplenishmentRequests.Create request,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader,
            JwtAuthenticationToken authentication) {
        String opId = OperationIds.resolve(request == null ? null : request.operationId(), operationId, operationHeader);
        return service.create(request, opId, operatorId(authentication));
    }

    @Operation(summary = "立即执行库存补货巡检")
    @PostMapping("/inspect")
    @PreAuthorize("hasAuthority('erp:replenishment:manage')")
    public Result<?> inspect(
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader,
            JwtAuthenticationToken authentication) {
        String opId = OperationIds.resolve(null, operationId, operationHeader);
        return service.inspect("MANUAL", opId, operatorId(authentication));
    }

    @Operation(summary = "补货任务转采购订单")
    @PostMapping("/{id}/create-order")
    @PreAuthorize("hasAuthority('erp:replenishment:manage')")
    public Result<?> createOrder(
            @PathVariable Long id,
            @RequestBody(required = false) ReplenishmentRequests.CreateOrder request,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader,
            JwtAuthenticationToken authentication) {
        String bodyOperationId = request == null ? null : request.operationId();
        String opId = OperationIds.resolve(bodyOperationId, operationId, operationHeader);
        return service.createOrder(id, request, opId, operatorId(authentication));
    }

    @Operation(summary = "完成补货任务")
    @PostMapping("/{id}/complete")
    @PreAuthorize("hasAuthority('erp:replenishment:manage')")
    public Result<?> complete(
            @PathVariable Long id,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader) {
        return service.complete(id, OperationIds.resolve(null, operationId, operationHeader));
    }

    @Operation(summary = "取消待处理补货任务")
    @PostMapping("/{id}/cancel")
    @PreAuthorize("hasAuthority('erp:replenishment:manage')")
    public Result<?> cancel(
            @PathVariable Long id,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader) {
        return service.cancel(id, OperationIds.resolve(null, operationId, operationHeader));
    }

    private static Long operatorId(JwtAuthenticationToken authentication) {
        if (authentication == null) return null;
        Object value = authentication.getToken().getClaims().get("user_id");
        if (value instanceof Number number) return number.longValue();
        if (value instanceof String text) {
            try { return Long.valueOf(text); } catch (NumberFormatException ignored) { return null; }
        }
        return null;
    }
}
