package com.motorparts.redis;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

@Service
public class ActivityService {
    private static final String PREFIX = "erp:activity:v1:";
    private static final Duration TTL = Duration.ofDays(30);
    private static final int RECENT_CAP = 20;
    private static final int FREQUENT_CAP = 100;

    private final StringRedisTemplate redis;

    public ActivityService(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public void recordPart(String subject, Long partId) {
        record(subject, "part", partId);
    }

    public void recordSupplier(String subject, Long supplierId) {
        record(subject, "supplier", supplierId);
    }

    public List<Long> recentParts(String subject, int limit) {
        return ids(recentKey(subject, "part"), limit);
    }

    public List<Long> frequentParts(String subject, int limit) {
        return ids(frequentKey(subject, "part"), limit);
    }

    public List<Long> recentSuppliers(String subject, int limit) {
        return ids(recentKey(subject, "supplier"), limit);
    }

    public List<Long> frequentSuppliers(String subject, int limit) {
        return ids(frequentKey(subject, "supplier"), limit);
    }

    private void record(String subject, String entity, Long entityId) {
        if (subject == null || subject.isBlank() || entityId == null) return;
        ZSetOperations<String, String> zsets = redis.opsForZSet();
        String member = entityId.toString();
        String recent = recentKey(subject, entity);
        String frequent = frequentKey(subject, entity);

        zsets.add(recent, member, System.currentTimeMillis());
        zsets.removeRange(recent, 0, -(RECENT_CAP + 1L));
        redis.expire(recent, TTL);

        zsets.incrementScore(frequent, member, 1D);
        zsets.removeRange(frequent, 0, -(FREQUENT_CAP + 1L));
        redis.expire(frequent, TTL);
    }

    private List<Long> ids(String key, int requestedLimit) {
        int limit = Math.max(1, Math.min(20, requestedLimit));
        Set<String> members = redis.opsForZSet().reverseRange(key, 0, limit - 1L);
        if (members == null || members.isEmpty()) return List.of();
        List<Long> ids = new ArrayList<>(members.size());
        for (String member : members) {
            try {
                ids.add(Long.valueOf(member));
            } catch (NumberFormatException ignored) {
                // Ignore corrupted members; catalog IDs are always numeric.
            }
        }
        return ids;
    }

    private static String recentKey(String subject, String entity) {
        return userPrefix(subject) + entity + ":recent";
    }

    private static String frequentKey(String subject, String entity) {
        return userPrefix(subject) + entity + ":frequent";
    }

    private static String userPrefix(String subject) {
        String normalized = subject == null ? "anonymous" : subject.trim();
        return PREFIX + RedisKeyHashes.sha256(normalized) + ":";
    }
}
