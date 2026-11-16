package com.motorparts.replenishment;

import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "motorparts.replenishment", name = "enabled", havingValue = "true", matchIfMissing = true)
public class ReplenishmentInspectionJob {
    private static final Logger log = LoggerFactory.getLogger(ReplenishmentInspectionJob.class);
    private final ReplenishmentService service;

    @Scheduled(cron = "${motorparts.replenishment.cron:0 0 2 * * *}",
            zone = "${motorparts.replenishment.zone:Asia/Shanghai}")
    public void inspect() {
        try {
            var result = service.inspect("SCHEDULED", null, null);
            log.info("定时补货巡检完成: code={}, message={}", result.getCode(), result.getMessage());
        } catch (Exception exception) {
            log.error("定时补货巡检失败", exception);
        }
    }
}
