package com.motorparts.procurement.expiry;

import com.motorparts.entity.PurchaseOrder;
import com.motorparts.service.PurchaseOrderService;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "motorparts.order-expiry", name = "enabled", havingValue = "true")
public class OrderExpiryJob {
    private static final Logger log = LoggerFactory.getLogger(OrderExpiryJob.class);

    private final OrderExpiryTaskService taskService;
    private final PurchaseOrderService purchaseOrderService;

    @Value("${motorparts.order-expiry.batch-size:20}")
    private int batchSize;

    @Scheduled(fixedDelayString = "${motorparts.order-expiry.poll-interval-ms:5000}")
    public void cancelExpiredPendingOrders() {
        for (OrderExpiryTask task : taskService.pollDue(batchSize)) {
            try {
                PurchaseOrder order = purchaseOrderService.getById(task.getOrderId());
                if (order != null && Integer.valueOf(1).equals(order.getStatus())) {
                    boolean changed = purchaseOrderService.updateOrderStatus(order.getId(), 5);
                    if (!changed) log.info("订单 {} 到期取消未生效，状态可能已变更", order.getId());
                }
                taskService.markDone(task.getId());
            } catch (Exception exception) {
                String message = exception.getMessage() == null
                        ? exception.getClass().getSimpleName()
                        : exception.getMessage();
                log.warn("处理订单到期任务 id={} 失败: {}", task.getId(), message);
                taskService.markFailed(task.getId(), message);
            }
        }
    }
}
