package com.motorparts.controller;

import com.motorparts.common.Result;
import com.motorparts.redis.LoginRateLimiter;
import com.motorparts.security.AuthService;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private static final String REFRESH_COOKIE = "erp_refresh";
    private final AuthService auth;
    private final LoginRateLimiter loginRateLimiter;
    private final boolean secureCookie;

    public AuthController(AuthService auth,
                          LoginRateLimiter loginRateLimiter,
                          @Value("${motorparts.security.cookie-secure:false}") boolean secureCookie) {
        this.auth = auth;
        this.loginRateLimiter = loginRateLimiter;
        this.secureCookie = secureCookie;
    }

    @PostMapping("/login")
    public ResponseEntity<Result<Map<String, Object>>> login(@Valid @RequestBody LoginRequest body,
                                                              HttpServletRequest request) {
        LoginRateLimiter.Decision rateLimit = loginRateLimiter.check(clientIp(request));
        if (!rateLimit.allowed()) {
            return ResponseEntity.status(429)
                    .header(HttpHeaders.RETRY_AFTER, String.valueOf(rateLimit.retryAfterSeconds()))
                    .body(Result.error(429, "登录尝试过于频繁，请稍后再试"));
        }
        try {
            return tokenResponse(auth.login(body.username(), body.password(), clientIp(request), request.getHeader("User-Agent")));
        } catch (AuthService.AuthenticationFailed ex) {
            return ResponseEntity.status(401).body(Result.error(401, "用户名、密码或账号状态无效"));
        }
    }

    @PostMapping("/refresh")
    public ResponseEntity<Result<Map<String, Object>>> refresh(HttpServletRequest request) {
        String raw = cookie(request, REFRESH_COOKIE);
        if (raw == null) return ResponseEntity.status(401).body(Result.error(401, "刷新会话无效"));
        try {
            return tokenResponse(auth.refresh(raw, clientIp(request), request.getHeader("User-Agent")));
        } catch (RuntimeException ex) {
            return ResponseEntity.status(401).header(HttpHeaders.SET_COOKIE, clearCookie().toString())
                    .body(Result.error(401, "刷新会话已失效，请重新登录"));
        }
    }

    @PostMapping("/logout")
    public ResponseEntity<Result<Void>> logout(HttpServletRequest request) {
        auth.logout(cookie(request, REFRESH_COOKIE));
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE, clearCookie().toString()).body(Result.success());
    }

    @PostMapping("/change-password")
    public ResponseEntity<Result<Void>> changePassword(@Valid @RequestBody ChangePasswordRequest body,
                                                        JwtAuthenticationToken authentication) {
        try {
            auth.changePassword(authentication.getToken().getSubject(), body.currentPassword(), body.newPassword());
            return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE, clearCookie().toString()).body(Result.success());
        } catch (AuthService.AuthenticationFailed ex) {
            return ResponseEntity.status(400).body(Result.error(400, "当前密码不正确"));
        }
    }

    @GetMapping("/me")
    public Result<Map<String, Object>> me(JwtAuthenticationToken authentication) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("subject", authentication.getToken().getSubject());
        data.put("username", authentication.getToken().getClaimAsString("username"));
        data.put("displayName", authentication.getToken().getClaimAsString("display_name"));
        data.put("roles", authentication.getToken().getClaimAsStringList("roles"));
        data.put("permissions", authentication.getToken().getClaimAsStringList("permissions"));
        data.put("authzVersion", authentication.getToken().getClaim("authz_version"));
        return Result.success(data);
    }

    private ResponseEntity<Result<Map<String, Object>>> tokenResponse(AuthService.TokenBundle bundle) {
        Map<String, Object> user = new LinkedHashMap<>();
        user.put("subject", bundle.principal().subject());
        user.put("username", bundle.principal().username());
        user.put("displayName", bundle.principal().displayName());
        user.put("roles", bundle.principal().roles());
        user.put("permissions", bundle.principal().permissions());
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("accessToken", bundle.accessToken());
        data.put("expiresAt", bundle.accessExpiresAt());
        data.put("user", user);
        ResponseCookie cookie = ResponseCookie.from(REFRESH_COOKIE, bundle.refreshToken()).httpOnly(true)
                .secure(secureCookie).sameSite("Strict").path("/api/auth")
                .maxAge(Duration.ofSeconds(Math.max(0, bundle.refreshExpiresAt() - java.time.Instant.now().getEpochSecond()))).build();
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE, cookie.toString()).body(Result.success(data));
    }

    private ResponseCookie clearCookie() {
        return ResponseCookie.from(REFRESH_COOKIE, "").httpOnly(true).secure(secureCookie)
                .sameSite("Strict").path("/api/auth").maxAge(Duration.ZERO).build();
    }

    private static String cookie(HttpServletRequest request, String name) {
        if (request.getCookies() == null) return null;
        return Arrays.stream(request.getCookies()).filter(c -> name.equals(c.getName())).map(Cookie::getValue).findFirst().orElse(null);
    }

    private static String clientIp(HttpServletRequest request) {
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) return realIp.trim();
        return request.getRemoteAddr();
    }

    public record LoginRequest(@NotBlank String username, @NotBlank String password) {}
    public record ChangePasswordRequest(@NotBlank String currentPassword,
                                        @NotBlank @Size(min = 10) String newPassword) {}
}
