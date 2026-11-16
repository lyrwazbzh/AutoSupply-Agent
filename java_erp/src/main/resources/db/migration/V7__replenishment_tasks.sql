-- M3 deterministic replenishment workflow.

DELIMITER $$
CREATE PROCEDURE `flyway_v7_order_supplier`()
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'purchase_order'
      AND COLUMN_NAME = 'supplier_id'
  ) THEN
    ALTER TABLE `purchase_order`
      ADD COLUMN `supplier_id` bigint DEFAULT NULL AFTER `order_number`;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'purchase_order'
      AND INDEX_NAME = 'idx_order_supplier_id'
  ) THEN
    ALTER TABLE `purchase_order`
      ADD KEY `idx_order_supplier_id` (`supplier_id`);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'purchase_order'
      AND CONSTRAINT_NAME = 'fk_order_supplier'
  ) THEN
    ALTER TABLE `purchase_order`
      ADD CONSTRAINT `fk_order_supplier` FOREIGN KEY (`supplier_id`) REFERENCES `supplier` (`id`)
        ON DELETE SET NULL ON UPDATE CASCADE;
  END IF;
END$$
DELIMITER ;

CALL `flyway_v7_order_supplier`();
DROP PROCEDURE `flyway_v7_order_supplier`;

CREATE TABLE IF NOT EXISTS `replenishment_task` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `task_no` varchar(64) NOT NULL,
  `part_id` bigint NOT NULL,
  `current_quantity` int NOT NULL,
  `safety_stock` int NOT NULL,
  `suggested_quantity` int NOT NULL,
  `preferred_supplier_id` bigint DEFAULT NULL,
  `reason` varchar(500) DEFAULT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'PENDING',
  `source` varchar(32) NOT NULL,
  `related_order_id` bigint DEFAULT NULL,
  `inspection_date` date DEFAULT NULL,
  `created_by` bigint DEFAULT NULL,
  `completed_at` datetime DEFAULT NULL,
  `operation_id` varchar(128) DEFAULT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `active_part_id` bigint GENERATED ALWAYS AS (
    CASE WHEN `status` IN ('PENDING', 'ORDER_CREATED') THEN `part_id` ELSE NULL END
  ) STORED,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_replenishment_task_no` (`task_no`),
  UNIQUE KEY `uk_replenishment_active_part` (`active_part_id`),
  UNIQUE KEY `uk_replenishment_operation` (`operation_id`),
  KEY `idx_replenishment_status_time` (`status`, `create_time`),
  KEY `idx_replenishment_part_time` (`part_id`, `create_time`),
  KEY `idx_replenishment_supplier` (`preferred_supplier_id`),
  KEY `idx_replenishment_order` (`related_order_id`),
  CONSTRAINT `fk_replenishment_part` FOREIGN KEY (`part_id`) REFERENCES `part` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_replenishment_supplier` FOREIGN KEY (`preferred_supplier_id`) REFERENCES `supplier` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_replenishment_order` FOREIGN KEY (`related_order_id`) REFERENCES `purchase_order` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_replenishment_creator` FOREIGN KEY (`created_by`) REFERENCES `user` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `ck_replenishment_current` CHECK (`current_quantity` >= 0),
  CONSTRAINT `ck_replenishment_safety` CHECK (`safety_stock` >= 0),
  CONSTRAINT `ck_replenishment_suggested` CHECK (`suggested_quantity` > 0),
  CONSTRAINT `ck_replenishment_status` CHECK (`status` IN ('PENDING','ORDER_CREATED','COMPLETED','CANCELLED')),
  CONSTRAINT `ck_replenishment_source` CHECK (`source` IN ('MANUAL','AUTO_INSPECTION'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `replenishment_inspection` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `run_no` varchar(64) NOT NULL,
  `source` varchar(32) NOT NULL,
  `started_at` datetime NOT NULL,
  `completed_at` datetime NOT NULL,
  `scanned_count` int NOT NULL DEFAULT 0,
  `low_stock_count` int NOT NULL DEFAULT 0,
  `created_count` int NOT NULL DEFAULT 0,
  `skipped_active_count` int NOT NULL DEFAULT 0,
  `missing_supplier_count` int NOT NULL DEFAULT 0,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_replenishment_inspection_run` (`run_no`),
  KEY `idx_replenishment_inspection_time` (`completed_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `security_permission` (`code`, `name`, `resource`, `action`) VALUES
  ('erp:replenishment:read', '查看补货任务', 'erp:replenishment', 'read'),
  ('erp:replenishment:manage', '管理补货任务', 'erp:replenishment', 'manage')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `resource` = VALUES(`resource`), `action` = VALUES(`action`);

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id` FROM `security_role` r CROSS JOIN `security_permission` p
WHERE r.`code` = 'ADMIN'
  AND p.`code` IN ('erp:replenishment:read', 'erp:replenishment:manage');

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id` FROM `security_role` r JOIN `security_permission` p
  ON p.`code` IN ('erp:replenishment:read', 'erp:replenishment:manage')
WHERE r.`code` = 'PURCHASER';

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id` FROM `security_role` r JOIN `security_permission` p
  ON p.`code` = 'erp:replenishment:read'
WHERE r.`code` IN ('WAREHOUSE', 'VIEWER');
