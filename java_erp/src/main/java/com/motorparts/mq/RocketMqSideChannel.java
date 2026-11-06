package com.motorparts.mq;

import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * RocketMQ 旁路通知。关闭或无 Template 时 no-op；永不替代 operation 回查。
 */
@Component
public class RocketMqSideChannel {

    private static final Logger log = LoggerFactory.getLogger(RocketMqSideChannel.class);

    private final ObjectProvider<RocketMQTemplate> rocketMQTemplate;
    private final boolean enabled;

    public RocketMqSideChannel(
            ObjectProvider<RocketMQTemplate> rocketMQTemplate,
            @Value("${motorparts.mq.rocketmq-enabled:false}") boolean enabled) {
        this.rocketMQTemplate = rocketMQTemplate;
        this.enabled = enabled;
    }

    public void publish(String topic, String payload) {
        if (!enabled) {
            return;
        }
        RocketMQTemplate template = rocketMQTemplate.getIfAvailable();
        if (template == null) {
            log.debug("RocketMQTemplate 不可用，跳过旁路发送 topic={}", topic);
            return;
        }
        try {
            template.convertAndSend(topic, payload);
        } catch (Exception e) {
            log.warn("RocketMQ 旁路发送失败 topic={}: {}", topic, e.getMessage());
        }
    }
}
