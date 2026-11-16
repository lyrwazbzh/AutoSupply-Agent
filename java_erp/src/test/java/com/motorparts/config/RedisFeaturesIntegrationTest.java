package com.motorparts.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.motorparts.cache.CatalogCacheNames;
import com.motorparts.entity.Part;
import com.motorparts.redis.ActivityService;
import com.motorparts.redis.LoginRateLimiter;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.data.redis.connection.RedisPassword;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

@Testcontainers(disabledWithoutDocker = true)
class RedisFeaturesIntegrationTest {
    private static final String PASSWORD = "redis-test-secret";

    @Container
    private static final GenericContainer<?> REDIS = new GenericContainer<>(DockerImageName.parse("redis:7-alpine"))
            .withExposedPorts(6379)
            .withCommand("redis-server", "--requirepass", PASSWORD, "--appendonly", "no");

    private static LettuceConnectionFactory connectionFactory;
    private static StringRedisTemplate redis;

    @BeforeAll
    static void connect() {
        RedisStandaloneConfiguration configuration = new RedisStandaloneConfiguration(
                REDIS.getHost(), REDIS.getMappedPort(6379));
        configuration.setPassword(RedisPassword.of(PASSWORD));
        connectionFactory = new LettuceConnectionFactory(configuration);
        connectionFactory.afterPropertiesSet();
        redis = new StringRedisTemplate(connectionFactory);
        redis.afterPropertiesSet();
    }

    @AfterAll
    static void disconnect() {
        if (connectionFactory != null) connectionFactory.destroy();
    }

    @Test
    void cacheUsesJsonTenMinuteTtlAndScanBasedClear() {
        ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
        CacheManager manager = new RedisCacheConfig().cacheManager(connectionFactory, mapper);
        Cache cache = manager.getCache(CatalogCacheNames.PART_DETAIL);
        assertNotNull(cache);

        Part part = new Part();
        part.setId(1L);
        part.setPartCode("P-1");
        part.setName("火花塞");
        part.setPurchasePrice(new BigDecimal("18.50"));
        part.setCreateTime(LocalDateTime.of(2026, 1, 2, 3, 4));
        cache.put("1", part);

        Part cached = cache.get("1", Part.class);
        assertNotNull(cached);
        assertEquals(new BigDecimal("18.50"), cached.getPurchasePrice());
        assertEquals(part.getCreateTime(), cached.getCreateTime());
        Long ttl = redis.getExpire("erp:cache:v1:part-detail::1", TimeUnit.SECONDS);
        assertNotNull(ttl);
        assertTrue(ttl > 0 && ttl <= 600);

        cache.clear();
        assertFalse(Boolean.TRUE.equals(redis.hasKey("erp:cache:v1:part-detail::1")));
    }

    @Test
    void loginRateLimitIsAtomicAndIsolatedByIp() {
        LoginRateLimiter limiter = new LoginRateLimiter(
                redis, new RedisScriptConfig().loginRateLimitScript(), 10, 60);
        LoginRateLimiter.Decision decision = null;
        for (int i = 0; i < 11; i++) {
            decision = limiter.check("203.0.113.10");
        }
        assertNotNull(decision);
        assertFalse(decision.allowed());
        assertEquals(11, decision.attempts());
        assertTrue(decision.retryAfterSeconds() > 0 && decision.retryAfterSeconds() <= 60);
        assertTrue(limiter.check("203.0.113.11").allowed());

        Set<String> keys = redis.keys("erp:security:v1:login-limit:*");
        assertNotNull(keys);
        assertTrue(keys.stream().noneMatch(key -> key.contains("203.0.113")));
    }

    @Test
    void activityIsSeparatedByUserAndEntityAndCapped() {
        ActivityService activity = new ActivityService(redis);
        for (long id = 1; id <= 25; id++) activity.recordPart("usr-a", id);
        activity.recordPart("usr-a", 25L);
        activity.recordPart("usr-a", 25L);
        activity.recordSupplier("usr-a", 7L);
        activity.recordPart("usr-b", 99L);

        List<Long> recentA = activity.recentParts("usr-a", 20);
        assertEquals(20, recentA.size());
        assertEquals(25L, activity.frequentParts("usr-a", 10).get(0));
        assertEquals(List.of(7L), activity.recentSuppliers("usr-a", 10));
        assertEquals(List.of(99L), activity.recentParts("usr-b", 10));
    }
}
