package com.motorparts.procurement.returnorder;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.OperationIds;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
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

import java.time.LocalDateTime;

@Tag(name = "采购退货")
@RestController
@RequestMapping("/api/purchase-returns")
@PreAuthorize("hasAuthority('erp:order:read')")
@RequiredArgsConstructor
public class PurchaseReturnController {
    private final PurchaseReturnService service;

    @Operation(summary = "分页查询采购退货单")
    @GetMapping("/page")
    public Result<PageResult<PurchaseReturn>> page(
            @RequestParam(defaultValue = "1") long current,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) Long orderId,
            @RequestParam(required = false) Long partId,
            @RequestParam(required = false) String reasonType,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
            LocalDateTime startTime,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
            LocalDateTime endTime) {
        Page<PurchaseReturn> page = service.page(current, size, status, orderId, partId,
                reasonType, startTime, endTime);
        return Result.success(PageResult.from(page));
    }

    @Operation(summary = "创建采购退货单")
    @PostMapping("/create")
    @PreAuthorize("hasAuthority('erp:order:return')")
    public Result<?> create(
            @RequestBody PurchaseReturnRequests.Create request,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader,
            JwtAuthenticationToken authentication) {
        String bodyOperationId = request == null ? null : request.operationId();
        String opId = OperationIds.resolve(bodyOperationId, operationId, operationHeader);
        return service.create(request, opId, operatorId(authentication));
    }

    @Operation(summary = "确认采购退货并扣减库存")
    @PostMapping("/{id}/confirm")
    @PreAuthorize("hasAuthority('erp:order:return')")
    public Result<?> confirm(
            @PathVariable Long id,
            @RequestParam(required = false) String operationId,
            @RequestHeader(value = "X-Operation-Id", required = false) String operationHeader,
            JwtAuthenticationToken authentication) {
        return service.confirm(id, OperationIds.resolve(null, operationId, operationHeader),
                operatorId(authentication));
    }

    private static Long operatorId(JwtAuthenticationToken authentication) {
        if (authentication == null) return null;
        Object value = authentication.getToken().getClaims().get("user_id");
        if (value instanceof Number number) return number.longValue();
        if (value instanceof String text) {
            try {
                return Long.valueOf(text);
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }
}
