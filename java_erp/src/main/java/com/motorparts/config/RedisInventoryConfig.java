package com.motorparts.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;

@Configuration
@ConditionalOnProperty(prefix = "motorparts.redis", name = "enabled", havingValue = "true")
public class RedisInventoryConfig {

    @Bean
    public LettuceConnectionFactory redisConnectionFactory(
            @org.springframework.beans.factory.annotation.Value("${spring.data.redis.host:localhost}") String host,
            @org.springframework.beans.factory.annotation.Value("${spring.data.redis.port:6379}") int port) {
        return new LettuceConnectionFactory(host, port);
    }

    @Bean
    public StringRedisTemplate stringRedisTemplate(RedisConnectionFactory factory) {
        return new StringRedisTemplate(factory);
    }

    @Bean
    public RedisScript<Long> inventoryOutboundScript() {
        DefaultRedisScript<Long> script = new DefaultRedisScript<>();
        script.setLocation(new ClassPathResource("lua/inventory_outbound.lua"));
        script.setResultType(Long.class);
        return script;
    }

    @Bean
    public RedisScript<Long> inventoryRollbackScript() {
        DefaultRedisScript<Long> script = new DefaultRedisScript<>();
        script.setLocation(new ClassPathResource("lua/inventory_rollback.lua"));
        script.setResultType(Long.class);
        return script;
    }
}
