package com.motorparts.mq;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.motorparts.entity.LocalMessage;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.service.PurchaseOrderService;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 扫描 local_message：到期执行待审核订单自动取消，并可选旁路推 RocketMQ。
 */
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "motorparts.mq", name = "enabled", havingValue = "true")
public class LocalMessageDispatchJob {

    private static final Logger log = LoggerFactory.getLogger(LocalMessageDispatchJob.class);

    private final LocalMessageService localMessageService;
    private final PurchaseOrderService purchaseOrderService;
    private final RocketMqSideChannel rocketMqSideChannel;
    private final ObjectMapper objectMapper;

    @Value("${motorparts.mq.poll-batch-size:20}")
    private int batchSize;

    @Scheduled(fixedDelayString = "${motorparts.mq.poll-interval-ms:5000}")
    public void dispatchDue() {
        List<LocalMessage> due = localMessageService.pollDue(batchSize);
        for (LocalMessage msg : due) {
            try {
                handle(msg);
                localMessageService.markDone(msg.getId());
                rocketMqSideChannel.publish(msg.getTopic(), msg.getPayload());
            } catch (Exception e) {
                log.warn("处理 local_message id={} 失败: {}", msg.getId(), e.getMessage());
                localMessageService.markFailed(msg.getId());
            }
        }
    }

    private void handle(LocalMessage msg) throws Exception {
        if (!LocalMessageService.TOPIC_ORDER_PENDING_CANCEL.equals(msg.getTopic())) {
            return;
        }
        JsonNode node = objectMapper.readTree(msg.getPayload());
        long orderId = node.path("orderId").asLong();
        PurchaseOrder order = purchaseOrderService.getById(orderId);
        if (order == null) {
            return;
        }
        // 仅待审核(1) 可自动取消 → 5
        if (order.getStatus() != null && order.getStatus() == 1) {
            boolean ok = purchaseOrderService.updateOrderStatus(orderId, 5);
            if (!ok) {
                log.info("订单 {} 自动取消未生效（状态可能已变更）", orderId);
            }
        }
    }
}
