-- Agent-Harness 写治理兼容：operation 回查 + 订单幂等
-- 可由 HarnessCompatMigrationRunner 自动执行；也可手工在 motorparts_db 执行。

CREATE TABLE IF NOT EXISTS `erp_operation` (
  `operation_id` varchar(128) NOT NULL COMMENT '网关操作号',
  `status` varchar(32) NOT NULL DEFAULT 'SUCCEEDED' COMMENT 'SUCCEEDED / NOT_FOUND 等',
  `applied` tinyint NOT NULL DEFAULT 0 COMMENT '1=已落库生效',
  `result_json` mediumtext COMMENT '首次成功响应 JSON',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`operation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='ERP 写操作回查';

CREATE TABLE IF NOT EXISTS `order_idempotency` (
  `idempotency_key` varchar(191) NOT NULL COMMENT '业务幂等键',
  `order_id` bigint NOT NULL COMMENT '绑定订单 ID',
  `payload_hash` varchar(128) NOT NULL COMMENT '业务载荷摘要',
  `status` varchar(32) NOT NULL DEFAULT 'CONFIRMED' COMMENT 'CONFIRMED / REJECTED',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`idempotency_key`),
  KEY `idx_order_id` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购订单幂等绑定';

-- purchase_order 幂等列（已存在则跳过；Runner 用 information_schema 判断）
-- ALTER TABLE `purchase_order` ADD COLUMN `idempotency_key` varchar(191) DEFAULT NULL COMMENT '幂等键';
-- ALTER TABLE `purchase_order` ADD COLUMN `payload_hash` varchar(128) DEFAULT NULL COMMENT '业务载荷摘要';
-- ALTER TABLE `purchase_order` ADD UNIQUE KEY `uk_idempotency_key` (`idempotency_key`);

CREATE TABLE IF NOT EXISTS `local_message` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `msg_key` varchar(191) NOT NULL COMMENT '业务唯一键',
  `topic` varchar(128) NOT NULL,
  `payload` text,
  `status` varchar(32) NOT NULL DEFAULT 'PENDING',
  `deliver_at` datetime NOT NULL,
  `retry_count` int NOT NULL DEFAULT 0,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_msg_key` (`msg_key`),
  KEY `idx_deliver` (`status`,`deliver_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='本地消息表（延迟取消/旁路）';
