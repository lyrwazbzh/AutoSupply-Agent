-- 不变式验收（在冒烟 curl 之后于 motorparts_db 执行）

-- 1) 同一 idempotency_key 至多绑定一张单
SELECT idempotency_key, COUNT(*) AS cnt
FROM order_idempotency
GROUP BY idempotency_key
HAVING COUNT(*) > 1;
-- 期望：0 行

-- 2) 库存不为负
SELECT id, part_id, current_quantity
FROM inventory
WHERE deleted = 0 AND current_quantity < 0;
-- 期望：0 行

-- 3) operation 已应用记录应有 result_json
SELECT operation_id
FROM erp_operation
WHERE applied = 1 AND (result_json IS NULL OR result_json = '');
-- 期望：0 行

-- 4) local_message msg_key 唯一（表约束）；查看待处理积压
SELECT status, COUNT(*) AS cnt
FROM local_message
GROUP BY status;
