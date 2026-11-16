package com.motorparts.redis;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
public class LoginRateLimiter {
    private static final String KEY_PREFIX = "erp:security:v1:login-limit:";

    private final StringRedisTemplate redis;
    private final RedisScript<List> script;
    private final int maxAttempts;
    private final int windowSeconds;

    public LoginRateLimiter(
            StringRedisTemplate redis,
            @Qualifier("loginRateLimitScript") RedisScript<List> script,
            @Value("${motorparts.security.login-rate-limit.max-attempts:10}") int maxAttempts,
            @Value("${motorparts.security.login-rate-limit.window-seconds:60}") int windowSeconds) {
        this.redis = redis;
        this.script = script;
        this.maxAttempts = Math.max(1, maxAttempts);
        this.windowSeconds = Math.max(1, windowSeconds);
    }

    public Decision check(String clientIp) {
        String normalized = clientIp == null || clientIp.isBlank() ? "unknown" : clientIp.trim();
        List<?> result = redis.execute(
                script,
                List.of(KEY_PREFIX + RedisKeyHashes.sha256(normalized)),
                String.valueOf(windowSeconds));
        if (result == null || result.size() < 2) {
            throw new IllegalStateException("Redis login rate-limit script returned no result");
        }
        long attempts = ((Number) result.get(0)).longValue();
        long ttl = Math.max(1L, ((Number) result.get(1)).longValue());
        return new Decision(attempts <= maxAttempts, attempts, ttl);
    }

    public record Decision(boolean allowed, long attempts, long retryAfterSeconds) {
    }
}
