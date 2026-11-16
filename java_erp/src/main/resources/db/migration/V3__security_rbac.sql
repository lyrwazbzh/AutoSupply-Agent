-- Unified identity, role and permission model.  The legacy `user`.`role`
-- stays for one compatibility release; the old password value is migrated
-- only when it is a recognized adaptive hash and is then erased.

DELIMITER $$
CREATE PROCEDURE `flyway_v3_security_columns`()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' AND COLUMN_NAME = 'auth_subject') THEN
    ALTER TABLE `user` ADD COLUMN `auth_subject` varchar(64) DEFAULT NULL AFTER `id`;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' AND COLUMN_NAME = 'password_hash') THEN
    ALTER TABLE `user` ADD COLUMN `password_hash` varchar(255) DEFAULT NULL AFTER `password`;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' AND COLUMN_NAME = 'authz_version') THEN
    ALTER TABLE `user` ADD COLUMN `authz_version` bigint NOT NULL DEFAULT 1;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' AND COLUMN_NAME = 'failed_login_count') THEN
    ALTER TABLE `user` ADD COLUMN `failed_login_count` int NOT NULL DEFAULT 0;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' AND COLUMN_NAME = 'locked_until') THEN
    ALTER TABLE `user` ADD COLUMN `locked_until` datetime DEFAULT NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' AND COLUMN_NAME = 'last_login_at') THEN
    ALTER TABLE `user` ADD COLUMN `last_login_at` datetime DEFAULT NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' AND COLUMN_NAME = 'password_changed_at') THEN
    ALTER TABLE `user` ADD COLUMN `password_changed_at` datetime DEFAULT NULL;
  END IF;
END$$
DELIMITER ;

CALL `flyway_v3_security_columns`();
DROP PROCEDURE `flyway_v3_security_columns`;

-- The old development initializer stored BCrypt hashes without Spring
-- Security's `{bcrypt}` id. Preserve only recognized adaptive hashes, then
-- erase the compatibility column. Unknown/plaintext formats require an
-- administrator reset and are never accepted as login credentials.
UPDATE `user`
SET `password_hash` = CASE
  WHEN `password` LIKE '{bcrypt}$2%' THEN `password`
  WHEN `password` LIKE '$2a$%' OR `password` LIKE '$2b$%' OR `password` LIKE '$2y$%'
    THEN CONCAT('{bcrypt}', `password`)
  ELSE `password_hash`
END
WHERE (`password_hash` IS NULL OR `password_hash` = '');

UPDATE `user` SET `password` = '!' WHERE `password` <> '!';

-- Preserve the current nginx-derived identity for existing conversations.
UPDATE `user`
SET `auth_subject` = CASE
  WHEN LEFT(REGEXP_REPLACE(`username`, '[^A-Za-z0-9_-]', ''), 24) = ''
    THEN CONCAT('user_', LEFT(SHA2(`username`, 256), 8))
  ELSE CONCAT(LEFT(REGEXP_REPLACE(`username`, '[^A-Za-z0-9_-]', ''), 24), '_', LEFT(SHA2(`username`, 256), 8))
END
WHERE `auth_subject` IS NULL OR `auth_subject` = '';

DELIMITER $$
CREATE PROCEDURE `flyway_v3_security_indexes`()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user' AND INDEX_NAME = 'uk_user_auth_subject') THEN
    ALTER TABLE `user` ADD UNIQUE KEY `uk_user_auth_subject` (`auth_subject`);
  END IF;
END$$
DELIMITER ;
CALL `flyway_v3_security_indexes`();
DROP PROCEDURE `flyway_v3_security_indexes`;

CREATE TABLE IF NOT EXISTS `security_role` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(64) NOT NULL,
  `name` varchar(100) NOT NULL,
  `description` varchar(500) DEFAULT NULL,
  `built_in` tinyint NOT NULL DEFAULT 0,
  `status` tinyint NOT NULL DEFAULT 1,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_security_role_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `security_permission` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(128) NOT NULL,
  `name` varchar(100) NOT NULL,
  `resource` varchar(64) NOT NULL,
  `action` varchar(64) NOT NULL,
  `description` varchar(500) DEFAULT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_security_permission_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `security_user_role` (
  `user_id` bigint NOT NULL,
  `role_id` bigint NOT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`, `role_id`),
  KEY `idx_security_user_role_role` (`role_id`),
  CONSTRAINT `fk_security_user_role_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_security_user_role_role` FOREIGN KEY (`role_id`) REFERENCES `security_role` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `security_role_permission` (
  `role_id` bigint NOT NULL,
  `permission_id` bigint NOT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`role_id`, `permission_id`),
  KEY `idx_security_role_permission_permission` (`permission_id`),
  CONSTRAINT `fk_security_role_permission_role` FOREIGN KEY (`role_id`) REFERENCES `security_role` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_security_role_permission_permission` FOREIGN KEY (`permission_id`) REFERENCES `security_permission` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `security_refresh_session` (
  `id` char(36) NOT NULL,
  `family_id` char(36) NOT NULL,
  `user_id` bigint NOT NULL,
  `token_hash` char(64) NOT NULL,
  `expires_at` datetime NOT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `replaced_by` char(36) DEFAULT NULL,
  `client_ip` varchar(64) DEFAULT NULL,
  `user_agent` varchar(500) DEFAULT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_security_refresh_hash` (`token_hash`),
  KEY `idx_security_refresh_user` (`user_id`, `expires_at`),
  KEY `idx_security_refresh_family` (`family_id`),
  CONSTRAINT `fk_security_refresh_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `security_external_identity` (
  `provider` varchar(64) NOT NULL,
  `external_subject` varchar(191) NOT NULL,
  `user_id` bigint NOT NULL,
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`provider`, `external_subject`),
  KEY `idx_security_external_user` (`user_id`),
  CONSTRAINT `fk_security_external_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `security_role` (`code`, `name`, `description`, `built_in`) VALUES
  ('ADMIN', '管理员', '系统与业务全部权限', 1),
  ('PURCHASER', '采购员', '供应商、零件和采购订单维护', 1),
  ('WAREHOUSE', '仓管员', '库存与物流操作', 1),
  ('VIEWER', '查看者', '业务只读与只读助手', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `description` = VALUES(`description`), `built_in` = 1;

INSERT INTO `security_permission` (`code`, `name`, `resource`, `action`) VALUES
 ('system:user:read','查看用户','system:user','read'),('system:user:manage','管理用户','system:user','manage'),
 ('system:role:read','查看角色','system:role','read'),('system:role:manage','管理角色','system:role','manage'),
 ('erp:supplier:read','查看供应商','erp:supplier','read'),('erp:supplier:write','维护供应商','erp:supplier','write'),('erp:supplier:status','变更供应商状态','erp:supplier','status'),
 ('erp:part:read','查看零件','erp:part','read'),('erp:part:write','维护零件','erp:part','write'),('erp:part:price','修改价格','erp:part','price'),
 ('erp:order:read','查看订单','erp:order','read'),('erp:order:create','创建订单','erp:order','create'),('erp:order:update','修改订单','erp:order','update'),('erp:order:delete','删除订单','erp:order','delete'),('erp:order:status','变更订单状态','erp:order','status'),('erp:order:approve','审批订单','erp:order','approve'),
 ('erp:inventory:read','查看库存','erp:inventory','read'),('erp:inventory:inbound','库存入库','erp:inventory','inbound'),('erp:inventory:outbound','库存出库','erp:inventory','outbound'),('erp:inventory:safety-stock','设置安全库存','erp:inventory','safety-stock'),
 ('erp:customer:read','查看客户','erp:customer','read'),('erp:customer:write','维护客户','erp:customer','write'),
 ('erp:logistics:read','查看物流','erp:logistics','read'),('erp:logistics:write','维护物流','erp:logistics','write'),
 ('erp:statistics:read','查看统计','erp:statistics','read'),('erp:operation:read','查看操作结果','erp:operation','read'),
 ('assistant:use','使用智能助手','assistant','use'),('assistant:erp-write','助手执行ERP写操作','assistant','erp-write'),
 ('audit:read:self','查看本人审计','audit','read:self'),('audit:read:all','查看全部审计','audit','read:all'),('audit:resolve','审计人工结案','audit','resolve')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `resource` = VALUES(`resource`), `action` = VALUES(`action`);

-- ADMIN receives every explicit permission; no wildcard authority is used.
INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `security_role` r CROSS JOIN `security_permission` p WHERE r.code = 'ADMIN';

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `security_role` r JOIN `security_permission` p ON p.code IN (
 'erp:supplier:read','erp:supplier:write','erp:supplier:status','erp:part:read','erp:part:write','erp:part:price',
 'erp:order:read','erp:order:create','erp:order:update','erp:order:delete','erp:order:status',
 'erp:inventory:read','erp:customer:read','erp:logistics:read','erp:statistics:read','erp:operation:read',
 'assistant:use','assistant:erp-write','audit:read:self') WHERE r.code = 'PURCHASER';

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `security_role` r JOIN `security_permission` p ON p.code IN (
 'erp:supplier:read','erp:part:read','erp:order:read','erp:inventory:read','erp:inventory:inbound',
 'erp:inventory:outbound','erp:inventory:safety-stock','erp:customer:read','erp:logistics:read','erp:logistics:write',
 'erp:statistics:read','erp:operation:read','assistant:use','assistant:erp-write','audit:read:self') WHERE r.code = 'WAREHOUSE';

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `security_role` r JOIN `security_permission` p ON p.code IN (
 'erp:supplier:read','erp:part:read','erp:order:read','erp:inventory:read','erp:customer:read',
 'erp:logistics:read','erp:statistics:read','erp:operation:read','assistant:use','audit:read:self') WHERE r.code = 'VIEWER';

-- Migrate the legacy single-role field without removing it yet.
INSERT IGNORE INTO `security_user_role` (`user_id`, `role_id`)
SELECT u.id, r.id FROM `user` u JOIN `security_role` r ON r.code = CASE LOWER(COALESCE(u.role, ''))
 WHEN 'admin' THEN 'ADMIN' WHEN 'purchase' THEN 'PURCHASER' WHEN 'warehouse' THEN 'WAREHOUSE' ELSE 'VIEWER' END;
