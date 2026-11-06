package com.motorparts.inventory;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.UUID;

/**
 * Redis Lua 热路径扣库存。正确性底线仍是 MySQL CAS；本组件失败/关闭时由 DB 路径兜底。
 */
@Component
@ConditionalOnProperty(prefix = "motorparts.redis", name = "enabled", havingValue = "true")
public class RedisInventoryGate {

    public static final long OK = 1L;
    public static final long INSUFFICIENT = 0L;
    public static final long IDEMPOTENT_HIT = 2L;

    private final StringRedisTemplate redis;
    private final RedisScript<Long> outboundScript;
    private final RedisScript<Long> rollbackScript;
    private final long idemTtlSeconds;

    @Autowired
    public RedisInventoryGate(
            StringRedisTemplate redis,
            @Qualifier("inventoryOutboundScript") RedisScript<Long> outboundScript,
            @Qualifier("inventoryRollbackScript") RedisScript<Long> rollbackScript,
            @Value("${motorparts.redis.idem-ttl-seconds:86400}") long idemTtlSeconds) {
        this.redis = redis;
        this.outboundScript = outboundScript;
        this.rollbackScript = rollbackScript;
        this.idemTtlSeconds = idemTtlSeconds;
    }

    public record GateResult(long code, String requestId) {
    }

    public GateResult tryOutbound(Long partId, int quantity, String requestId) {
        String rid = (requestId == null || requestId.isBlank())
                ? UUID.randomUUID().toString()
                : requestId;
        Long code = redis.execute(
                outboundScript,
                Arrays.asList(stockKey(partId), idemKey(rid)),
                String.valueOf(quantity),
                rid,
                String.valueOf(idemTtlSeconds)
        );
        return new GateResult(code == null ? -1L : code, rid);
    }

    public void rollbackOutbound(Long partId, int quantity, String requestId) {
        redis.execute(
                rollbackScript,
                Arrays.asList(stockKey(partId), idemKey(requestId)),
                String.valueOf(quantity)
        );
    }

    public void syncStock(Long partId, int currentQuantity) {
        redis.opsForValue().set(stockKey(partId), String.valueOf(Math.max(0, currentQuantity)));
    }

    private static String stockKey(Long partId) {
        return "inv:" + partId;
    }

    private static String idemKey(String requestId) {
        return "idem:outbound:" + requestId;
    }
}
