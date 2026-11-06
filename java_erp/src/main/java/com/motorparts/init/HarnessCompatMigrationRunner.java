package com.motorparts.init;

import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 启动时确保 Harness 写治理表/列存在（幂等 DDL）。
 * 在 DatabaseInitializer 建表之后执行。
 */
@Component
@Order(Ordered.LOWEST_PRECEDENCE)
@RequiredArgsConstructor
public class HarnessCompatMigrationRunner implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(HarnessCompatMigrationRunner.class);

    private final JdbcTemplate jdbcTemplate;

    @Override
    public void run(ApplicationArguments args) {
        jdbcTemplate.execute(
                "CREATE TABLE IF NOT EXISTS `erp_operation` (" +
                        "  `operation_id` varchar(128) NOT NULL," +
                        "  `status` varchar(32) NOT NULL DEFAULT 'SUCCEEDED'," +
                        "  `applied` tinyint NOT NULL DEFAULT 0," +
                        "  `result_json` mediumtext," +
                        "  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP," +
                        "  PRIMARY KEY (`operation_id`)" +
                        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
        );
        jdbcTemplate.execute(
                "CREATE TABLE IF NOT EXISTS `order_idempotency` (" +
                        "  `idempotency_key` varchar(191) NOT NULL," +
                        "  `order_id` bigint NOT NULL," +
                        "  `payload_hash` varchar(128) NOT NULL," +
                        "  `status` varchar(32) NOT NULL DEFAULT 'CONFIRMED'," +
                        "  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP," +
                        "  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP," +
                        "  PRIMARY KEY (`idempotency_key`)," +
                        "  KEY `idx_order_id` (`order_id`)" +
                        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
        );
        addColumnIfMissing("purchase_order", "idempotency_key",
                "ALTER TABLE `purchase_order` ADD COLUMN `idempotency_key` varchar(191) DEFAULT NULL COMMENT '幂等键'");
        addColumnIfMissing("purchase_order", "payload_hash",
                "ALTER TABLE `purchase_order` ADD COLUMN `payload_hash` varchar(128) DEFAULT NULL COMMENT '业务载荷摘要'");
        addUniqueIfMissing("purchase_order", "uk_idempotency_key",
                "ALTER TABLE `purchase_order` ADD UNIQUE KEY `uk_idempotency_key` (`idempotency_key`)");
        jdbcTemplate.execute(
                "CREATE TABLE IF NOT EXISTS `local_message` (" +
                        "  `id` bigint NOT NULL AUTO_INCREMENT," +
                        "  `msg_key` varchar(191) NOT NULL," +
                        "  `topic` varchar(128) NOT NULL," +
                        "  `payload` text," +
                        "  `status` varchar(32) NOT NULL DEFAULT 'PENDING'," +
                        "  `deliver_at` datetime NOT NULL," +
                        "  `retry_count` int NOT NULL DEFAULT 0," +
                        "  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP," +
                        "  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP," +
                        "  PRIMARY KEY (`id`)," +
                        "  UNIQUE KEY `uk_msg_key` (`msg_key`)," +
                        "  KEY `idx_deliver` (`status`,`deliver_at`)" +
                        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
        );
        log.info("Harness 写治理表/列与 local_message 已就绪");
    }

    private void addColumnIfMissing(String table, String column, String ddl) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(1) FROM information_schema.COLUMNS " +
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?",
                Integer.class, table, column);
        if (count == null || count == 0) {
            jdbcTemplate.execute(ddl);
        }
    }

    private void addUniqueIfMissing(String table, String indexName, String ddl) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(1) FROM information_schema.STATISTICS " +
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND INDEX_NAME = ?",
                Integer.class, table, indexName);
        if (count == null || count == 0) {
            try {
                jdbcTemplate.execute(ddl);
            } catch (Exception e) {
                log.warn("添加唯一索引 {} 跳过: {}", indexName, e.getMessage());
            }
        }
    }
}
