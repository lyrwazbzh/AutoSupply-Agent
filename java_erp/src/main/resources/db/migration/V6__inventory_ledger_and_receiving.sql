-- M2 inventory ledger and atomic purchase-order receiving.

CREATE TABLE IF NOT EXISTS `inventory_transaction` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `transaction_no` varchar(64) NOT NULL,
  `part_id` bigint NOT NULL,
  `transaction_type` varchar(32) NOT NULL,
  `quantity` int NOT NULL,
  `before_quantity` int NOT NULL,
  `after_quantity` int NOT NULL,
  `source_type` varchar(32) DEFAULT NULL,
  `source_id` bigint DEFAULT NULL,
  `operation_id` varchar(128) DEFAULT NULL,
  `operator_id` bigint DEFAULT NULL,
  `warehouse_location` varchar(100) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  `occurred_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_inventory_transaction_no` (`transaction_no`),
  UNIQUE KEY `uk_inventory_transaction_operation` (`operation_id`, `part_id`, `transaction_type`),
  KEY `idx_inventory_transaction_part_time` (`part_id`, `occurred_at`),
  KEY `idx_inventory_transaction_source` (`source_type`, `source_id`),
  KEY `idx_inventory_transaction_operation` (`operation_id`),
  KEY `idx_inventory_transaction_operator` (`operator_id`),
  CONSTRAINT `fk_inventory_transaction_part` FOREIGN KEY (`part_id`) REFERENCES `part` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_inventory_transaction_operator` FOREIGN KEY (`operator_id`) REFERENCES `user` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `ck_inventory_transaction_quantity` CHECK (`quantity` > 0),
  CONSTRAINT `ck_inventory_transaction_before` CHECK (`before_quantity` >= 0),
  CONSTRAINT `ck_inventory_transaction_after` CHECK (`after_quantity` >= 0),
  CONSTRAINT `ck_inventory_transaction_type` CHECK (`transaction_type` IN ('PURCHASE_RECEIPT','MANUAL_INBOUND','MANUAL_OUTBOUND','PURCHASE_RETURN','STOCK_ADJUSTMENT'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `security_permission` (`code`, `name`, `resource`, `action`) VALUES
  ('erp:order:receive', '采购订单确认收货', 'erp:order', 'receive'),
  ('erp:inventory:transaction:read', '查看库存流水', 'erp:inventory:transaction', 'read')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `resource` = VALUES(`resource`), `action` = VALUES(`action`);

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id`
FROM `security_role` r CROSS JOIN `security_permission` p
WHERE r.`code` = 'ADMIN'
  AND p.`code` IN ('erp:order:receive', 'erp:inventory:transaction:read');

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id`
FROM `security_role` r JOIN `security_permission` p
  ON p.`code` = 'erp:inventory:transaction:read'
WHERE r.`code` IN ('PURCHASER', 'WAREHOUSE', 'VIEWER');

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id`
FROM `security_role` r JOIN `security_permission` p
  ON p.`code` = 'erp:order:receive'
WHERE r.`code` = 'WAREHOUSE';
