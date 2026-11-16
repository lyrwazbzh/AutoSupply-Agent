-- M1 procurement catalog: multi-supplier quotations and motorcycle fitments.
-- Existing part.supplier_id remains the compatibility/default-supplier field.

CREATE TABLE IF NOT EXISTS `supplier_part` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `supplier_id` bigint NOT NULL,
  `part_id` bigint NOT NULL,
  `supplier_part_code` varchar(100) DEFAULT NULL,
  `purchase_price` decimal(12,2) NOT NULL DEFAULT 0.00,
  `minimum_order_quantity` int NOT NULL DEFAULT 1,
  `lead_time_days` int DEFAULT NULL,
  `quality_rating` decimal(3,2) DEFAULT NULL,
  `last_purchase_time` datetime DEFAULT NULL,
  `enabled` tinyint NOT NULL DEFAULT 1,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_supplier_part` (`supplier_id`, `part_id`),
  KEY `idx_supplier_part_part_enabled` (`part_id`, `enabled`),
  KEY `idx_supplier_part_supplier_enabled` (`supplier_id`, `enabled`),
  KEY `idx_supplier_part_price_lead` (`part_id`, `purchase_price`, `lead_time_days`),
  CONSTRAINT `fk_supplier_part_supplier` FOREIGN KEY (`supplier_id`) REFERENCES `supplier` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_supplier_part_part` FOREIGN KEY (`part_id`) REFERENCES `part` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `ck_supplier_part_price` CHECK (`purchase_price` >= 0),
  CONSTRAINT `ck_supplier_part_moq` CHECK (`minimum_order_quantity` >= 1),
  CONSTRAINT `ck_supplier_part_lead_time` CHECK (`lead_time_days` IS NULL OR `lead_time_days` >= 0),
  CONSTRAINT `ck_supplier_part_quality` CHECK (`quality_rating` IS NULL OR (`quality_rating` >= 0 AND `quality_rating` <= 5))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `vehicle_model` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `brand` varchar(100) NOT NULL,
  `series` varchar(100) DEFAULT NULL,
  `model` varchar(100) NOT NULL,
  `model_year_start` int DEFAULT NULL,
  `model_year_end` int DEFAULT NULL,
  `displacement` int DEFAULT NULL COMMENT 'engine displacement in cc',
  `engine_code` varchar(100) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  `deleted` tinyint NOT NULL DEFAULT 0,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_vehicle_brand_series_model` (`brand`, `series`, `model`),
  KEY `idx_vehicle_year` (`model_year_start`, `model_year_end`),
  KEY `idx_vehicle_displacement` (`displacement`),
  KEY `idx_vehicle_engine_code` (`engine_code`),
  CONSTRAINT `ck_vehicle_year_range` CHECK (`model_year_start` IS NULL OR `model_year_end` IS NULL OR `model_year_start` <= `model_year_end`),
  CONSTRAINT `ck_vehicle_displacement` CHECK (`displacement` IS NULL OR `displacement` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `part_fitment` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `part_id` bigint NOT NULL,
  `vehicle_model_id` bigint NOT NULL,
  `fitment_note` varchar(500) DEFAULT NULL,
  `verified` tinyint NOT NULL DEFAULT 0,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_part_fitment` (`part_id`, `vehicle_model_id`),
  KEY `idx_fitment_vehicle_part` (`vehicle_model_id`, `part_id`),
  CONSTRAINT `fk_fitment_part` FOREIGN KEY (`part_id`) REFERENCES `part` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_fitment_vehicle` FOREIGN KEY (`vehicle_model_id`) REFERENCES `vehicle_model` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Preserve all current default supplier assignments without overwriting any
-- manually-created quotation rows in legacy environments.
INSERT INTO `supplier_part` (
  `supplier_id`, `part_id`, `supplier_part_code`, `purchase_price`,
  `minimum_order_quantity`, `enabled`
)
SELECT p.`supplier_id`, p.`id`, p.`part_code`, p.`purchase_price`, 1,
       CASE WHEN s.`status` = 1 AND s.`deleted` = 0 THEN 1 ELSE 0 END
FROM `part` p
JOIN `supplier` s ON s.`id` = p.`supplier_id`
WHERE p.`supplier_id` IS NOT NULL AND p.`deleted` = 0
ON DUPLICATE KEY UPDATE `id` = `supplier_part`.`id`;

INSERT INTO `security_permission` (`code`, `name`, `resource`, `action`) VALUES
  ('erp:vehicle:read', '查看车型', 'erp:vehicle', 'read'),
  ('erp:vehicle:write', '维护车型', 'erp:vehicle', 'write'),
  ('erp:fitment:read', '查看零件适配', 'erp:fitment', 'read'),
  ('erp:fitment:write', '维护零件适配', 'erp:fitment', 'write'),
  ('erp:supplier-part:read', '查看供应商报价', 'erp:supplier-part', 'read'),
  ('erp:supplier-part:write', '维护供应商报价', 'erp:supplier-part', 'write')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `resource` = VALUES(`resource`), `action` = VALUES(`action`);

-- Built-in role grants are explicit so newly introduced permissions are not
-- accidentally omitted from ADMIN after V3 has already run.
INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id`
FROM `security_role` r CROSS JOIN `security_permission` p
WHERE r.`code` = 'ADMIN'
  AND p.`code` IN ('erp:vehicle:read','erp:vehicle:write','erp:fitment:read','erp:fitment:write','erp:supplier-part:read','erp:supplier-part:write');

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id`
FROM `security_role` r JOIN `security_permission` p
  ON p.`code` IN ('erp:vehicle:read','erp:vehicle:write','erp:fitment:read','erp:fitment:write','erp:supplier-part:read','erp:supplier-part:write')
WHERE r.`code` = 'PURCHASER';

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id`
FROM `security_role` r JOIN `security_permission` p
  ON p.`code` IN ('erp:vehicle:read','erp:fitment:read','erp:supplier-part:read')
WHERE r.`code` IN ('WAREHOUSE', 'VIEWER');
