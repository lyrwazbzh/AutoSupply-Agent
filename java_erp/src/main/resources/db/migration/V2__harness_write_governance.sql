CREATE TABLE IF NOT EXISTS `erp_operation` (
  `operation_id` varchar(128) NOT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'SUCCEEDED',
  `applied` tinyint NOT NULL DEFAULT 0,
  `result_json` mediumtext,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`operation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `order_idempotency` (
  `idempotency_key` varchar(191) NOT NULL,
  `order_id` bigint NOT NULL,
  `payload_hash` varchar(128) NOT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'CONFIRMED',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`idempotency_key`),
  KEY `idx_order_id` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `local_message` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `msg_key` varchar(191) NOT NULL,
  `topic` varchar(128) NOT NULL,
  `payload` text,
  `status` varchar(32) NOT NULL DEFAULT 'PENDING',
  `deliver_at` datetime NOT NULL,
  `retry_count` int NOT NULL DEFAULT 0,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_msg_key` (`msg_key`),
  KEY `idx_deliver` (`status`, `deliver_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Existing installations may already have any subset of these changes. A stored
-- procedure lets the migration remain safe on all supported MySQL 8.0 patch levels.
DELIMITER $$
CREATE PROCEDURE `flyway_v2_harness_compat`()
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'purchase_order'
      AND COLUMN_NAME = 'idempotency_key'
  ) THEN
    ALTER TABLE `purchase_order`
      ADD COLUMN `idempotency_key` varchar(191) DEFAULT NULL COMMENT '幂等键';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'purchase_order'
      AND COLUMN_NAME = 'payload_hash'
  ) THEN
    ALTER TABLE `purchase_order`
      ADD COLUMN `payload_hash` varchar(128) DEFAULT NULL COMMENT '业务载荷摘要';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'purchase_order'
      AND INDEX_NAME = 'uk_idempotency_key'
  ) THEN
    ALTER TABLE `purchase_order`
      ADD UNIQUE KEY `uk_idempotency_key` (`idempotency_key`);
  END IF;
END$$
DELIMITER ;

CALL `flyway_v2_harness_compat`();
DROP PROCEDURE `flyway_v2_harness_compat`;

