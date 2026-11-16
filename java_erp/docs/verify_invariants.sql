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

-- 4) order_expiry_task task_key 唯一（表约束）；查看待处理积压
SELECT status, COUNT(*) AS cnt
FROM order_expiry_task
GROUP BY status;

-- 5) 库存流水前后数量必须与变动方向一致
SELECT id, transaction_no, transaction_type, quantity, before_quantity, after_quantity
FROM inventory_transaction
WHERE before_quantity < 0 OR after_quantity < 0
   OR (transaction_type IN ('PURCHASE_RECEIPT', 'MANUAL_INBOUND')
       AND after_quantity <> before_quantity + quantity)
   OR (transaction_type IN ('MANUAL_OUTBOUND', 'PURCHASE_RETURN')
       AND after_quantity <> before_quantity - quantity);
-- 期望：0 行

-- 6) 每个零件的最新流水余额应与当前库存一致
SELECT i.part_id, i.current_quantity, latest.after_quantity, latest.transaction_no
FROM inventory i
JOIN inventory_transaction latest ON latest.id = (
    SELECT it.id FROM inventory_transaction it
    WHERE it.part_id = i.part_id
    ORDER BY it.occurred_at DESC, it.id DESC LIMIT 1
)
WHERE i.deleted = 0 AND i.current_quantity <> latest.after_quantity;
-- 期望：0 行

-- 7) 带 operationId 的库存流水必须有已完成的 operation 结果
SELECT it.transaction_no, it.operation_id
FROM inventory_transaction it
LEFT JOIN erp_operation op ON op.operation_id = it.operation_id AND op.applied = 1
WHERE it.operation_id IS NOT NULL AND op.operation_id IS NULL;
-- 期望：0 行

-- 8) 每个零件最多一个未完成补货任务（同时由生成列唯一索引兜底）
SELECT part_id, COUNT(*) AS active_count
FROM replenishment_task
WHERE status IN ('PENDING', 'ORDER_CREATED')
GROUP BY part_id
HAVING COUNT(*) > 1;
-- 期望：0 行

-- 9) 已转订单任务必须有真实采购单，且供应商一致
SELECT rt.id, rt.task_no, rt.related_order_id, rt.preferred_supplier_id, po.supplier_id
FROM replenishment_task rt
LEFT JOIN purchase_order po ON po.id = rt.related_order_id AND po.deleted = 0
WHERE rt.status = 'ORDER_CREATED'
  AND (po.id IS NULL OR NOT (rt.preferred_supplier_id <=> po.supplier_id));
-- 期望：0 行

-- 10) 补货数量始终为正且不低于任务生成时的确定性建议
SELECT id, task_no, suggested_quantity
FROM replenishment_task
WHERE suggested_quantity <= 0;
-- 期望：0 行

-- 11) 同一采购单、同一零件的累计已确认退货不能超过原采购数量
SELECT returned.purchase_order_id, returned.part_id,
       returned.returned_quantity, ordered.ordered_quantity
FROM (
    SELECT purchase_order_id, part_id, SUM(quantity) AS returned_quantity
    FROM purchase_return
    WHERE status = 'CONFIRMED'
    GROUP BY purchase_order_id, part_id
) returned
LEFT JOIN (
    SELECT order_id, part_id, SUM(quantity) AS ordered_quantity
    FROM order_detail
    WHERE deleted = 0
    GROUP BY order_id, part_id
) ordered ON ordered.order_id = returned.purchase_order_id
         AND ordered.part_id = returned.part_id
WHERE ordered.order_id IS NULL OR returned.returned_quantity > ordered.ordered_quantity;
-- 期望：0 行

-- 12) 每张已确认退货单必须存在一条匹配的采购退货库存流水
SELECT pr.id, pr.return_number, pr.part_id, pr.quantity
FROM purchase_return pr
LEFT JOIN inventory_transaction it
  ON it.source_type = 'PURCHASE_RETURN'
 AND it.source_id = pr.id
 AND it.transaction_type = 'PURCHASE_RETURN'
 AND it.part_id = pr.part_id
 AND it.quantity = pr.quantity
WHERE pr.status = 'CONFIRMED' AND it.id IS NULL;
-- 期望：0 行

-- 13) 采购退货流水必须反向指向状态、零件和数量均一致的已确认退货单
SELECT it.id, it.transaction_no, it.source_id, it.part_id, it.quantity
FROM inventory_transaction it
LEFT JOIN purchase_return pr ON pr.id = it.source_id
WHERE it.transaction_type = 'PURCHASE_RETURN'
  AND (it.source_type <> 'PURCHASE_RETURN'
       OR pr.id IS NULL
       OR pr.status <> 'CONFIRMED'
       OR pr.part_id <> it.part_id
       OR pr.quantity <> it.quantity);
-- 期望：0 行
