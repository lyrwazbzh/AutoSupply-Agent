-- Remove the out-of-scope retail customer domain and replace the generic
-- local_message/RocketMQ abstraction with a dedicated pending-order expiry task.

CREATE TABLE IF NOT EXISTS `order_expiry_task` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `task_key` varchar(191) NOT NULL,
  `order_id` bigint NOT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'PENDING',
  `expire_at` datetime NOT NULL,
  `retry_count` int NOT NULL DEFAULT 0,
  `last_error` varchar(1000) DEFAULT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_expiry_task_key` (`task_key`),
  KEY `idx_order_expiry_due` (`status`, `expire_at`),
  KEY `idx_order_expiry_order` (`order_id`),
  CONSTRAINT `fk_order_expiry_order` FOREIGN KEY (`order_id`) REFERENCES `purchase_order` (`id`) ON DELETE CASCADE,
  CONSTRAINT `ck_order_expiry_status` CHECK (`status` IN ('PENDING','DONE','FAILED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

DROP PROCEDURE IF EXISTS `flyway_v9_cleanup_legacy`;
DELIMITER $$
CREATE PROCEDURE `flyway_v9_cleanup_legacy`()
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'local_message'
  ) THEN
    INSERT IGNORE INTO `order_expiry_task`
      (`task_key`, `order_id`, `status`, `expire_at`, `retry_count`, `last_error`, `create_time`, `update_time`)
    SELECT
      lm.`msg_key`,
      po.`id`,
      CASE WHEN lm.`status` = 'FAILED' THEN 'FAILED'
           WHEN lm.`status` IN ('DONE', 'SENT') THEN 'DONE'
           ELSE 'PENDING' END,
      lm.`deliver_at`, lm.`retry_count`, NULL, lm.`create_time`, lm.`update_time`
    FROM `local_message` lm
    JOIN `purchase_order` po
      ON po.`id` = CAST(JSON_UNQUOTE(JSON_EXTRACT(
           CASE WHEN JSON_VALID(lm.`payload`) THEN lm.`payload` ELSE NULL END,
           '$.orderId'
         )) AS UNSIGNED)
    WHERE lm.`topic` = 'order.pending.cancel'
      AND JSON_VALID(lm.`payload`)
      AND JSON_EXTRACT(lm.`payload`, '$.orderId') IS NOT NULL;
    DROP TABLE `local_message`;
  END IF;

  DELETE FROM `security_permission`
  WHERE `code` IN ('erp:customer:read', 'erp:customer:write');

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'customer'
  ) THEN
    DROP TABLE `customer`;
  END IF;
END$$
DELIMITER ;

CALL `flyway_v9_cleanup_legacy`();
DROP PROCEDURE `flyway_v9_cleanup_legacy`;
