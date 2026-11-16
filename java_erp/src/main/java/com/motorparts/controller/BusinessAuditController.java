package com.motorparts.controller;

import com.motorparts.common.Result;
import com.motorparts.security.BusinessAuditService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/audit")
@RequiredArgsConstructor
public class BusinessAuditController {
    private final BusinessAuditService audit;

    @GetMapping
    @PreAuthorize("hasAnyAuthority('audit:read:self','audit:read:all')")
    public Result<List<Map<String, Object>>> list(@RequestParam(required = false) String actor,
                                                  @RequestParam(required = false) String action,
                                                  @RequestParam(required = false) String outcome,
                                                  @RequestParam(defaultValue = "100") int limit,
                                                  JwtAuthenticationToken authentication) {
        boolean all = authentication.getAuthorities().stream().anyMatch(a -> "audit:read:all".equals(a.getAuthority()));
        String effectiveActor = all ? actor : authentication.getToken().getSubject();
        return Result.success(audit.list(effectiveActor, action, outcome, limit));
    }
}

