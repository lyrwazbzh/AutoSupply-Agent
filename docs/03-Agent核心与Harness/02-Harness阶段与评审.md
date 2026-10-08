# Harness 阶段与评审

Harness 在主图 state 里写入 `phase` / `plan` / `review_result`，需要时塞入 `rubric` 字符串。是否审查、审哪类在 `harness_review.py` 分开算；条文与门槛在 `harness_config.yaml`。打分与「不通过则打回」由其后的框架 `RubricMiddleware` 完成。`chat.py` 从 `values` 流读这些字段推 SSE；阶段进 Checkpointer，刷新后仍可接着看。

代码：`src/agent/harness.py`、`harness_review.py`、`harness_config.yaml`；类型 `src/agent/schema.py`（`Phase` / `Plan` / `ReviewResult`）；装配 `src/agent/main_agent.py`（`HarnessPhaseMiddleware` 在健康检查之后、`RubricMiddleware` 之前；再读 YAML 取 `review.max_iterations`）。委派角色名见 `04/01`（与本篇 `task_types` 是两套标签）。

出现非空 `state.rubric`，grader 才会跑。出现 `_harness_rubric_source="auto"`，表示本中间件注入的自动条文，简单请求可清空。

---

## 1. 解决什么问题

前端要跟规划 / 执行 / 审查 / 完成；业务任务对照完成标准打回重做；问候与短定义跳过 grader。阶段写进图字段，可 checkpoint、可观测。改审查政策改 YAML；阶段流转写在中间件钩子里。

| 层 | 职责 |
|----|------|
| `harness_config.yaml` | mode、门槛、例句、`task_types`、`rubrics`、`max_iterations` |
| `harness_review` | `should_use_grader`、`detect_task_type`（与 Store 无关） |
| `HarnessPhaseMiddleware` | 写 phase / plan / rubric / review_result |
| `RubricMiddleware` | 有 rubric 才跑 grader；`needs_revision` 打回 |
| `chat.py` | `values` → SSE；`PHASE_LABELS` 文案 |

---

## 2. 架构 / 数据流

```text
YAML → load_harness_config
  review.* / 例句 → should_use_grader
  task_types + rubrics → detect_task_type → build_rubric
  max_iterations → RubricMiddleware
  ↓
before_agent：phase=planning；按需写或清空 rubric
  ↓
模型 / 工具
after_model：tool_calls → executing；todos → plan
  ↓
RubricMiddleware（state.rubric 非空才跑 grader）
  ↓
after_agent（逆序，读 _rubric_status）
  review_result；reviewing 或 result
  ↓
values → chat.py SSE；Checkpointer 按 thread_id 保存
```

`TodoListMiddleware` 写 `todos`；Harness 收成 `state.plan`。装配顺序要求：`HarnessPhaseMiddleware` 在前、`RubricMiddleware` 在后，这样 `after_agent` 逆序时 Harness 能读到已更新的 `_rubric_status`。

---

## 3. 核心设计与实现

### 3.1 阶段机：`HarnessPhaseMiddleware`

扩展 state、读 YAML、按需写入 `rubric`，并把 phase / plan / review_result 写进可 checkpoint 的字段。真正打分打回不在本文件。

**`HarnessPhaseState`（经 `state_schema` 合并进图）**

| 字段 | 含义 |
|------|------|
| `phase` | 当前阶段字符串 |
| `plan` | 结构化计划 dict（`Plan.model_dump()`） |
| `review_result` | 评审结果 dict |
| `_harness_rubric_source` | 私有；`"auto"` 表示本中间件注入 |

**`load_harness_config`。** 读旁路 `harness_config.yaml`。文件不存在、解析失败或根不是 dict → `_DEFAULT_CONFIG`（`max_iterations=3`、空 `task_types`、一条 default rubric）。建图在缺文件时仍可完成。

**`build_rubric(task_type, config)`。** 取 `rubrics[task_type]`，没有则用 `default`，`strip()` 后返回。

**`_build_plan_from_todos`。** 空 → `None`；每项 → `step-{i}`（content / status）；第一个 `in_progress` → `current_step`；返回 `Plan.model_dump()`。

**钩子。**

| 钩子 | 行为 |
|------|------|
| `before_agent` | `phase=planning`。已有 rubric、无 auto 来源、无 `_active_rubric` → 视为外部显式 rubric，只返回 planning。`should_use_grader` 为假 → 清空遗留自动 rubric / 来源 / `review_result`。为真 → `detect_task_type` → `build_rubric`，非空则写 rubric + `_harness_rubric_source="auto"` |
| `after_model` | 末条有 `tool_calls` → `executing`；有 `todos` → 同步 `plan` |
| `after_agent` | 当前仍有 `rubric` 时才读 `_rubric_status`，用 `_rubric_evaluations` 末条填 `ReviewResult`。`needs_revision` → `reviewing`；其余 → `result`；再同步 `plan` |

```text
before_agent → planning → 写/清 rubric
after_model  → executing（有 tool_calls）→ plan ← todos
RubricMiddleware（rubric 非空）
after_agent  → review_result → reviewing | result
```

### 3.2 YAML：审查政策

| 键 | 缺省 / 含义 | 谁读 |
|----|-------------|------|
| `review.mode` | `auto` / `always` / `never` | `should_use_grader` |
| `t_skip` / `t_grade` | 0.55 / 0.40；正负例句 | `vector_should_grade` |
| `t_type` | 0.50 | `detect_task_type` 向量支 |
| `examples_need_review` / `examples_skip_review` | 需审 / 跳过例句 | 向量支 |
| `task_types.*.keywords` / `examples` | 子串计分；0 分才用例句向量 | `detect_task_type` |
| `rubrics.*` | 无该类型则 `default` | `build_rubric` |
| `review.max_iterations` | 3 | `RubricMiddleware` |
| `phases` | name + label | 与 `chat.py` 的 `PHASE_LABELS` 文案对齐 |

`mode=auto` 时：规则层已决则不走向量；无配置 `trigger_keywords` 时用 `harness_review` 内默认业务词表。

**`task_types`（rubric 分类）：** analysis、order、inventory、supplier、mrp、sourcing、delivery、quality。关键词可重叠；并列最高分 → `"default"` 通用条文。这与四个子 Agent 的 `name`（`task(subagent_type=...)`）是两套标签。`memory/extractor.py` 另有平行词表，不 import 本 YAML。

**`rubrics` 共性：** 真实工具数据、结论可执行。analysis 侧重清洗/表格/图表匹配；order 侧重字段完整、`request_order_info`、写操作走审批；mrp / sourcing / delivery / quality 侧重真实计划/报价/交付/PPAP 及风险表述。改 YAML 即改「什么叫过审」。

`review.model`：主 Agent 使用 `get_llm(thinking=False)` 的 `grader_llm`。阶段落库由 `chat.py` 写 `harness_traces`。

### 3.3 审查判定：`harness_review.py`

文本怎么抽、要不要开 grader、开了选哪类 rubric，都在这里算。出口两个：`should_use_grader`、`detect_task_type`。

**文本。** `_message_text`：多模态 list 只拼 `type==text` 块。`human_texts` / `latest_human_text`。`review_text`：无用户话 → `""`；否则取末句；至少两句且末句含跟进标记（再、也来、还是、那个、那家、上次、继续…）→ `rewrite_retrieval_query(当前, 上一句)`。

**规则辅助。** 问候 fullmatch；复合动作词（列出/查询/统计/分析…）；短定义「什么是 X」且无复合动作；业务实体（SKU/物料/订单号/工厂等）。

**`rule_grade_decision`。** 空 → False；问候 → False；定义句 + 复合动词 → True；短定义 → False；业务实体 → True；其它 → `None`（交给向量或关键词）。

**向量支 `vector_should_grade`。** 无 embedder 或例句空 → `None`；skip 相似 > `t_skip` 且高于 need → False；need 相似 > `t_grade` → True；已编码且不落前两支 → True。

**`should_use_grader`（要不要写 rubric）：**

```text
mode == never     → False
mode == always    → 有用户文本则 True
无 review_text    → False
规则已决          → 用规则
向量已决          → 用向量
否则              → 是否含触发关键词
```

**`detect_task_type`（已决定要审时选类型名）：**

```text
无 task_types / 审查文本空 → "default"
keywords 子串计分
  唯一最高分 > 0     → 该类型
  最高分 > 0 且并列   → "default"（结束，不上向量）
  全 0 分
      embedder 空 / 编码失败 / 最高相似 ≤ t_type / 向量并列
          → "default"
      唯一最高且过门槛 → 该类型
```

```text
messages → review_text（跟进句可改写）
        → should_use_grader：规则 → 向量 → 关键词
        → True 时 detect_task_type：keywords →（全 0 才）例句向量
        → 类型名 → build_rubric
```

### 3.4 `RubricMiddleware`（框架，装配侧）

`create_main_agent`：`grader_llm = get_llm(thinking=False)`；`RubricMiddleware(model=grader_llm, max_iterations=…)`。state-driven：`rubric` 非空才跑 grader 子 Agent，产出 `_rubric_status` / `_rubric_evaluations`；`needs_revision` 时打回模型重做，形成 Review 回路。轮数上限来自 YAML `review.max_iterations`（默认 3）。

### 3.5 类型合同：`schema.py`（Harness 段）

| 类型 | 用途 |
|------|------|
| `Phase` | `thinking` / `planning` / `executing` / `reviewing` / `result`。中间件写后四者；`thinking` 由 chat 开流发出 |
| `PlanStep` / `Plan` | todos 结构化快照；`current_step` 指向首个 in_progress |
| `ReviewResult` | `verdict`（satisfied / needs_revision / failed / max_iterations_reached / grader_error）、`explanation`、`criteria`、`iteration` |

HTTP / 会话类型（`ChatRequest`、`ProcurementContext` 等）见入口与装配篇；本篇依赖的是 Phase / Plan / ReviewResult。

---

## 4. 关键设计取舍

| 取舍 | 现行做法 |
|------|----------|
| grader 触发 | 看 state 里有没有非空 rubric；闲聊清空自动 rubric |
| 开关与类型 | 两段函数：先 `should_use_grader`，再 `detect_task_type` |
| 政策 vs 流转 | YAML 管审查政策；钩子管 planning → executing → reviewing/result |
| 观测 | 阶段写进图字段；SSE 比较 `phase` 变化再推 |
| 显式 rubric | 调用方写入且无 auto 来源时，`before_agent` 保留原文 |

---

## 5. 工程边界

| 主题 | 现行行为 |
|------|----------|
| `after_agent` 顺序 | 钩子逆序执行；Rubric 须挂在 Harness **之后**，Harness 才能读到 `_rubric_status` |
| 跟进句 | `review_text` + `rewrite_retrieval_query`；多模态只拼 text 块 |
| SSE 文案 | 改 YAML `phases.label` 时同步改 `chat.py` 的 `PHASE_LABELS` 才能反映到前端 |
| 权威实现 | 根目录 `harness.py` + 独立 `harness_review.py`；仓库内若另有历史树拷贝，审查开关与选型以根目录为准 |
| 嵌入依赖 | 向量支依赖 `DEFAULT_MEMORY_CONFIG` 的 HTTP embedder；未配置时规则/关键词仍可决 |

---

## 6. 面试记忆点

**thinking 谁写？**  
枚举含 `thinking`；中间件写后四者。SSE thinking 是 chat 开流动画。

**「你好」会不会跑 grader？**  
`auto` 下 `should_use_grader` 为假，清空遗留自动 rubric。

**显式 rubric？**  
调用方写入且无 auto 来源时，`before_agent` 保留原文，不跑自动选型。

**`task_types` 和四个子 Agent？**  
前者选 rubric 段落；后者是 `task` 的 `subagent_type`（见 04）。

**收束。** YAML 是审查政策；`harness_review` 判定要不要审、审哪类；`HarnessPhaseMiddleware` 写可恢复的阶段与计划；打分打回在 `RubricMiddleware`。复习时先对节 2 时序，再对 3.1 钩子与 3.3 两段判定。
