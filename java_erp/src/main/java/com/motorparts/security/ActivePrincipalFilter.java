package com.motorparts.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.motorparts.common.Result;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
@RequiredArgsConstructor
public class ActivePrincipalFilter extends OncePerRequestFilter {
    private final SecurityUserRepository users;
    private final ObjectMapper objectMapper;

    @Value("${motorparts.security.enabled:true}")
    private boolean enabled;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (enabled && authentication instanceof JwtAuthenticationToken jwt) {
            SecurityPrincipal current = users.findBySubject(jwt.getToken().getSubject()).orElse(null);
            Number version = jwt.getToken().getClaim("authz_version");
            if (current == null || !current.active() || version == null || current.authzVersion() != version.longValue()) {
                SecurityContextHolder.clearContext();
                response.setStatus(401);
                response.setContentType("application/json;charset=UTF-8");
                objectMapper.writeValue(response.getOutputStream(), Result.error(401, "登录状态或权限已经变更，请重新登录"));
                return;
            }
        }
        chain.doFilter(request, response);
    }
}

