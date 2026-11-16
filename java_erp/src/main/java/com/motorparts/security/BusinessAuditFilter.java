package com.motorparts.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;
import java.util.UUID;

@Component
@RequiredArgsConstructor
public class BusinessAuditFilter extends OncePerRequestFilter {
    private static final Logger log = LoggerFactory.getLogger(BusinessAuditFilter.class);
    private final BusinessAuditService audit;

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String method = request.getMethod();
        String path = request.getRequestURI();
        boolean mutation = !List.of("GET", "HEAD", "OPTIONS").contains(method);
        return !mutation || !(path.startsWith("/api/") || path.startsWith("/internal/"));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String requestId = safeId(request.getHeader("X-Request-ID"));
        response.setHeader("X-Request-ID", requestId);
        Throwable failure = null;
        try {
            chain.doFilter(request, response);
        } catch (Throwable ex) {
            failure = ex;
            if (ex instanceof IOException io) throw io;
            if (ex instanceof ServletException servlet) throw servlet;
            throw new ServletException(ex);
        } finally {
            try {
                Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
                JwtAuthenticationToken jwt = authentication instanceof JwtAuthenticationToken value ? value : null;
                List<String> roles = jwt == null || jwt.getToken().getClaimAsStringList("roles") == null
                        ? List.of() : jwt.getToken().getClaimAsStringList("roles");
                int status = response.getStatus();
                String outcome = failure != null || status >= 500 ? "FAILED" : status >= 400 ? "DENIED" : "SUCCESS";
                String path = request.getRequestURI();
                String[] segments = path.split("/");
                String resource = segments.length > 2 ? segments[2] : "unknown";
                audit.append(new BusinessAuditService.AuditEvent(
                        jwt == null ? null : jwt.getToken().getSubject(),
                        jwt == null ? null : jwt.getToken().getClaimAsString("username"), roles,
                        "ASSISTANT".equalsIgnoreCase(request.getHeader("X-Operation-Source")) ? "ASSISTANT" : "ERP_UI",
                        request.getMethod() + " " + path, resource, null, requestId,
                        request.getHeader("X-Trace-ID"), request.getHeader("X-Operation-ID"), request.getMethod(), path,
                        outcome, status, failure == null ? null : failure.getClass().getSimpleName(),
                        failure == null ? null : failure.getMessage(), clientIp(request), request.getHeader("User-Agent")));
            } catch (Exception auditFailure) {
                log.error("Failed to persist business audit event requestId={}", requestId, auditFailure);
            }
        }
    }

    private static String safeId(String value) {
        return value != null && value.matches("[A-Za-z0-9_-]{1,64}") ? value : UUID.randomUUID().toString();
    }
    private static String clientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        return forwarded == null || forwarded.isBlank() ? request.getRemoteAddr() : forwarded.split(",")[0].trim();
    }
}

