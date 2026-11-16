-- M4 lightweight purchase-return workflow.

CREATE TABLE IF NOT EXISTS `purchase_return` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `return_number` varchar(64) NOT NULL,
  `purchase_order_id` bigint NOT NULL,
  `part_id` bigint NOT NULL,
  `quantity` int NOT NULL,
  `reason_type` varchar(32) NOT NULL,
  `reason` varchar(500) DEFAULT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'PENDING',
  `operation_id` varchar(128) DEFAULT NULL,
  `confirm_operation_id` varchar(128) DEFAULT NULL,
  `created_by` bigint DEFAULT NULL,
  `confirmed_by` bigint DEFAULT NULL,
  `confirmed_at` datetime DEFAULT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_purchase_return_number` (`return_number`),
  UNIQUE KEY `uk_purchase_return_operation` (`operation_id`),
  UNIQUE KEY `uk_purchase_return_confirm_operation` (`confirm_operation_id`),
  KEY `idx_purchase_return_order_part` (`purchase_order_id`, `part_id`),
  KEY `idx_purchase_return_status_time` (`status`, `create_time`),
  KEY `idx_purchase_return_creator` (`created_by`),
  CONSTRAINT `fk_purchase_return_order` FOREIGN KEY (`purchase_order_id`) REFERENCES `purchase_order` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_purchase_return_part` FOREIGN KEY (`part_id`) REFERENCES `part` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_purchase_return_creator` FOREIGN KEY (`created_by`) REFERENCES `user` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_purchase_return_confirmer` FOREIGN KEY (`confirmed_by`) REFERENCES `user` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `ck_purchase_return_quantity` CHECK (`quantity` > 0),
  CONSTRAINT `ck_purchase_return_reason_type` CHECK (`reason_type` IN ('QUANTITY_MISMATCH','DAMAGED','SPEC_MISMATCH','QUALITY_ISSUE','OTHER')),
  CONSTRAINT `ck_purchase_return_status` CHECK (`status` IN ('PENDING','CONFIRMED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `security_permission` (`code`, `name`, `resource`, `action`) VALUES
  ('erp:order:return', '采购退货', 'erp:order', 'return')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `resource` = VALUES(`resource`), `action` = VALUES(`action`);

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id` FROM `security_role` r CROSS JOIN `security_permission` p
WHERE r.`code` = 'ADMIN' AND p.`code` = 'erp:order:return';

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id` FROM `security_role` r JOIN `security_permission` p
  ON p.`code` = 'erp:order:return'
WHERE r.`code` IN ('PURCHASER', 'WAREHOUSE');
