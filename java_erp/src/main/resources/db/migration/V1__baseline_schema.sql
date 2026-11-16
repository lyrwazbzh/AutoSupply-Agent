-- Canonical base schema for the procurement ERP. The application user connects to
-- an already-created database; database creation belongs to the deployment layer.

CREATE TABLE IF NOT EXISTS `user` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `username` varchar(50) NOT NULL,
  `password` varchar(100) NOT NULL,
  `real_name` varchar(50) DEFAULT NULL,
  `role` varchar(50) DEFAULT 'purchase',
  `department` varchar(50) DEFAULT '采购部',
  `phone` varchar(20) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `deleted` tinyint DEFAULT 0,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`),
  KEY `idx_user_role` (`role`),
  KEY `idx_user_department` (`department`),
  KEY `idx_user_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `supplier` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `supplier_code` varchar(50) NOT NULL,
  `name` varchar(100) NOT NULL,
  `contact_person` varchar(50) DEFAULT NULL,
  `phone` varchar(20) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `address` varchar(200) DEFAULT NULL,
  `credit_rating` char(1) DEFAULT 'B',
  `status` tinyint DEFAULT 1,
  `deleted` tinyint DEFAULT 0,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_supplier_code` (`supplier_code`),
  KEY `idx_supplier_status` (`status`),
  KEY `idx_supplier_credit_rating` (`credit_rating`),
  KEY `idx_supplier_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `part` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `part_code` varchar(50) NOT NULL,
  `name` varchar(100) NOT NULL,
  `model` varchar(100) DEFAULT NULL,
  `specification` varchar(200) DEFAULT NULL,
  `unit` varchar(20) DEFAULT '个',
  `purchase_price` decimal(10,2) NOT NULL DEFAULT 0.00,
  `suggested_retail_price` decimal(10,2) DEFAULT 0.00,
  `stock_warning_value` int DEFAULT 10,
  `supplier_id` bigint DEFAULT NULL,
  `category` varchar(50) DEFAULT NULL,
  `description` text,
  `deleted` tinyint DEFAULT 0,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_part_code` (`part_code`),
  KEY `idx_part_supplier_id` (`supplier_id`),
  KEY `idx_part_category` (`category`),
  KEY `idx_part_create_time` (`create_time`),
  CONSTRAINT `fk_part_supplier` FOREIGN KEY (`supplier_id`) REFERENCES `supplier` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `purchase_order` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `order_number` varchar(50) NOT NULL,
  `total_amount` decimal(12,2) DEFAULT 0.00,
  `status` tinyint DEFAULT 1,
  `order_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `expected_delivery_date` date DEFAULT NULL,
  `actual_delivery_date` date DEFAULT NULL,
  `created_by` bigint DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  `deleted` tinyint DEFAULT 0,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_number` (`order_number`),
  KEY `idx_order_status` (`status`),
  KEY `idx_order_time` (`order_time`),
  KEY `idx_order_created_by` (`created_by`),
  CONSTRAINT `fk_order_created_by` FOREIGN KEY (`created_by`) REFERENCES `user` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `order_detail` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `order_id` bigint NOT NULL,
  `part_id` bigint NOT NULL,
  `quantity` int NOT NULL DEFAULT 1,
  `unit_price` decimal(10,2) NOT NULL DEFAULT 0.00,
  `subtotal` decimal(12,2) GENERATED ALWAYS AS (`quantity` * `unit_price`) STORED,
  `remark` varchar(200) DEFAULT NULL,
  `deleted` tinyint DEFAULT 0,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_part` (`order_id`, `part_id`),
  KEY `idx_detail_order_id` (`order_id`),
  KEY `idx_detail_part_id` (`part_id`),
  CONSTRAINT `fk_detail_order` FOREIGN KEY (`order_id`) REFERENCES `purchase_order` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_detail_part` FOREIGN KEY (`part_id`) REFERENCES `part` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `inventory` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `part_id` bigint NOT NULL,
  `current_quantity` int NOT NULL DEFAULT 0,
  `safety_stock` int DEFAULT 10,
  `last_inbound_time` datetime DEFAULT NULL,
  `last_outbound_time` datetime DEFAULT NULL,
  `warehouse_location` varchar(100) DEFAULT 'A区-1号库',
  `deleted` tinyint DEFAULT 0,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_part_id` (`part_id`),
  KEY `idx_inventory_quantity` (`current_quantity`),
  KEY `idx_inventory_location` (`warehouse_location`),
  CONSTRAINT `fk_inventory_part` FOREIGN KEY (`part_id`) REFERENCES `part` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `customer` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `customer_code` varchar(50) NOT NULL,
  `name` varchar(100) NOT NULL,
  `contact_person` varchar(50) DEFAULT NULL,
  `phone` varchar(20) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `address` varchar(200) DEFAULT NULL,
  `customer_type` tinyint DEFAULT 1,
  `discount_level` tinyint DEFAULT 1,
  `registered_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `deleted` tinyint DEFAULT 0,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_customer_code` (`customer_code`),
  KEY `idx_customer_type` (`customer_type`),
  KEY `idx_customer_discount_level` (`discount_level`),
  KEY `idx_customer_registered_time` (`registered_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `logistics` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `order_id` bigint NOT NULL,
  `logistics_company` varchar(100) DEFAULT NULL,
  `tracking_number` varchar(100) DEFAULT NULL,
  `ship_time` datetime DEFAULT NULL,
  `estimated_arrival_time` datetime DEFAULT NULL,
  `actual_arrival_time` datetime DEFAULT NULL,
  `status` tinyint DEFAULT 1,
  `receiver` varchar(100) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  `deleted` tinyint DEFAULT 0,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_logistics_order_id` (`order_id`),
  KEY `idx_logistics_tracking_number` (`tracking_number`),
  KEY `idx_logistics_status` (`status`),
  KEY `idx_logistics_ship_time` (`ship_time`),
  CONSTRAINT `fk_logistics_order` FOREIGN KEY (`order_id`) REFERENCES `purchase_order` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE OR REPLACE VIEW `inventory_warning_view` AS
SELECT i.id, i.part_id, p.part_code, p.name AS part_name, i.current_quantity,
       i.safety_stock, p.stock_warning_value, i.warehouse_location,
       CASE WHEN i.current_quantity <= p.stock_warning_value THEN '严重不足'
            WHEN i.current_quantity <= i.safety_stock THEN '不足' ELSE '充足' END AS stock_status,
       i.last_inbound_time, i.last_outbound_time
FROM inventory i JOIN part p ON i.part_id = p.id
WHERE i.deleted = 0 AND p.deleted = 0;

CREATE OR REPLACE VIEW `order_statistics_view` AS
SELECT DATE(o.order_time) AS order_date, COUNT(*) AS order_count,
       SUM(o.total_amount) AS total_amount, AVG(o.total_amount) AS avg_amount
FROM purchase_order o WHERE o.deleted = 0 GROUP BY DATE(o.order_time);

CREATE OR REPLACE VIEW `order_detail_full_view` AS
SELECT od.id AS detail_id, od.order_id, o.order_number, od.part_id, p.part_code,
       p.name AS part_name, p.model, p.specification, od.quantity, od.unit_price,
       od.subtotal, p.supplier_id, s.name AS supplier_name, s.supplier_code,
       od.create_time AS detail_create_time
FROM order_detail od
JOIN purchase_order o ON od.order_id = o.id
JOIN part p ON od.part_id = p.id
LEFT JOIN supplier s ON p.supplier_id = s.id
WHERE od.deleted = 0 AND o.deleted = 0 AND p.deleted = 0;

