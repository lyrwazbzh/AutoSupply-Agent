---
name: shortage-disposition
description: 零部件缺料预警与采购处置——按口径计算缺口并生成可审批补货建议
scope: procurement
version: 2.0.0
caliber: shortage-口径/v2
---

# 缺料处置技能

## 适用条件

- 用户任务涉及车型窗口内缺料、齐套、补货建议
- 已具备或可澄清：`vehicle_model`、`plant_id`；`horizon_days` 默认 7

## 工具顺序

1. 槽位齐全后调用 `shortage_calc`（或先 `shortage_context` 再解释数据）
2. 缺口数量、建议量、齐套率、金额 **只引用** `verified_facts` / `verified_summary`；禁止心算改数
3. 对 `net_gap > 0` 且 `constraints_ok = false` 的行，说明约束原因，再给可选动作
4. 输出 Markdown 表格：物料、峰值需求、峰值可用供给、峰值缺口、首次缺料日、建议量、风险、约束、证据
5. 摘要中必须带 `calc_run_id` 与 `caliber_version`

## 写操作（M2）

```text
shortage_calc → freeze_shortage_suggestion → order_create(order_payload) → HITL → order_get 回查
```

1. 调用 `freeze_shortage_suggestion`，传入完整 calc JSON，得到固化 `order_payload`
2. **原样**将 `order_payload` 作为 `order_create` 的 `order_data`（勿改 quantity/unitPrice）
3. `blocked_lines` 不得写单；HITL 审批通过后执行建单；同一 key 同内容返回原订单，同 key 异内容必须拒绝
4. 正常响应后用 `order_get` 回查；超时或 `UNKNOWN` 时只用 `order_get_by_idempotency` 回查，禁止盲目重试

## 知识检索（按需）

- 常规缺料数字：仅 ERP + `shortage_calc`
- 制度 / 规格 / 准入：`search_business_knowledge`；看 `evidence_assessment`，不足则按返回的 bounded_react_policy 再检索（禁止写 ERP）
- 业务数据缺失：ERP 重查或明确说明；引用须带 source/version

## 演示种子

- 车型 `A-125`，工厂 `PLANT-HZ`
- v2 口径文档：`docs/shortage-口径-v2.md`；v1 文档仅用于历史回放
