-- Restrict global knowledge mutation and runtime Skill installation to explicit admins.
INSERT INTO `security_permission` (`code`, `name`, `resource`, `action`) VALUES
  ('assistant:knowledge:write', '助手知识入库', 'assistant:knowledge', 'write'),
  ('assistant:skill:install', '助手安装用户技能', 'assistant:skill', 'install')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `resource` = VALUES(`resource`), `action` = VALUES(`action`);

INSERT IGNORE INTO `security_role_permission` (`role_id`, `permission_id`)
SELECT r.`id`, p.`id`
FROM `security_role` r CROSS JOIN `security_permission` p
WHERE r.`code` = 'ADMIN'
  AND p.`code` IN ('assistant:knowledge:write', 'assistant:skill:install');
