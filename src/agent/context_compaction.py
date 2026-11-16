"""采购 Agent 的显式上下文压缩策略。

DeepAgents 会为 ``create_deep_agent`` 自动安装通用摘要中间件。这里创建一个
同名实例，由框架按名称原位替换默认实例，从而让阈值、保留窗口和摘要契约都由
项目控制。完整的原始历史仍由 DeepAgents 写入 ``/conversation_history/``；摘要
只负责模型上下文续接，不能作为 ERP 写操作、审批或幂等状态的事实源。
"""

from __future__ import annotations

from dataclasses import dataclass

from deepagents.middleware.summarization import (
    DEEPAGENTS_DEFAULT_SUMMARY_PROMPT,
    SummarizationMiddleware,
)

from .config import (
    CONTEXT_COMPACTION_KEEP_RATIO,
    CONTEXT_COMPACTION_TRIGGER_RATIO,
    CONTEXT_SUMMARY_SCHEMA_VERSION,
    LLM_CONTEXT_WINDOW_TOKENS,
)


@dataclass(frozen=True, slots=True)
class ContextCompactionSettings:
    """压缩窗口配置，比例最终转换为绝对 token 数。"""

    context_window_tokens: int = LLM_CONTEXT_WINDOW_TOKENS
    trigger_ratio: float = CONTEXT_COMPACTION_TRIGGER_RATIO
    keep_ratio: float = CONTEXT_COMPACTION_KEEP_RATIO
    schema_version: str = CONTEXT_SUMMARY_SCHEMA_VERSION

    def validate(self) -> None:
        if self.context_window_tokens <= 0:
            raise ValueError("LLM_CONTEXT_WINDOW_TOKENS must be greater than 0")
        if not 0 < self.keep_ratio < self.trigger_ratio < 1:
            raise ValueError(
                "context compaction ratios must satisfy "
                "0 < keep_ratio < trigger_ratio < 1"
            )
        if not self.schema_version:
            raise ValueError("CONTEXT_SUMMARY_SCHEMA_VERSION must not be empty")
        if self.keep_tokens >= self.trigger_tokens:
            raise ValueError("context compaction keep tokens must be below trigger tokens")

    @property
    def trigger_tokens(self) -> int:
        return int(self.context_window_tokens * self.trigger_ratio)

    @property
    def keep_tokens(self) -> int:
        return int(self.context_window_tokens * self.keep_ratio)


DEFAULT_CONTEXT_COMPACTION_SETTINGS = ContextCompactionSettings()


PROCUREMENT_CONTEXT_CONTRACT = """<procurement_context_contract>
The replacement context MUST use the following headings. Write "None" when a
section has no information. Do not omit a heading.

## SUMMARY SCHEMA
{schema_version}

## USER GOAL
The user's current procurement or inventory goal.

## CONFIRMED CONSTRAINTS
Confirmed budget, quantity, delivery date, brand, vehicle fitment, warehouse,
quality, supplier, and other requirements. Keep rejected options and their
reasons so they are not proposed again.

## ERP BUSINESS ENTITIES
Preserve exact names and identifiers whenever present, including partId,
partCode, supplierId, supplierCode, orderId, orderNo, replenishment task IDs,
return IDs, inventory transaction IDs, and vehicle model IDs.

## VERIFIED BUSINESS FACTS
Only facts supported by an ERP/MCP tool result or explicit knowledge evidence.
Keep exact quantities, monetary values and currencies, dates, status values,
and the supporting tool or record identifier. Conflicting facts must both be
kept and marked as requiring verification. The newest authoritative ERP/MCP
result takes precedence over older conversational wording.

## WRITE OPERATIONS AND IDEMPOTENCY
Preserve each operationId, idempotencyKey, tool name, target record, requested
change, execution status, result, or failure reason exactly. A proposed or
requested write must never be described as completed.

## APPROVAL STATE
Preserve pending approval operations, approval targets, current approval
status, approved or rejected outcomes, and information still required from the
user. A tool request is not proof that approval or execution succeeded.

## COMPLETED WORK
Queries, calculations and operations already completed, with their verified
results, so they are not repeated.

## OPEN WORK AND CLARIFICATIONS
Concrete next actions, unresolved questions, missing fields and blocked work.

## ARTIFACTS
Relevant files, reports and history references created or accessed.

Hard rules:
- Preserve IDs, codes, quantities, monetary values, currencies, dates and enum
  status values verbatim. Never translate, normalize or invent them.
- Separate user intentions and recommendations from verified business facts.
- Never turn a failed tool call into success or a recommendation into an ERP
  record.
- Write unknown values as "Unknown" instead of inferring them.
- Never include passwords, access tokens, private keys or database credentials.
- This summary is continuity context only. ERP, audit and approval stores remain
  the source of truth for any future write.
</procurement_context_contract>"""


def build_procurement_summary_prompt(schema_version: str) -> str:
    """在 DeepAgents 默认提示词中插入采购领域契约。

    ``<messages>`` 与 ``{messages}`` 是 DeepAgents/LangChain 的公开契约；基于
    默认模板插入而不是另写一份，可继续保留历史文件和媒体引用说明。
    """

    contract = PROCUREMENT_CONTEXT_CONTRACT.format(schema_version=schema_version)
    marker = "\n<messages>\n"
    if marker not in DEEPAGENTS_DEFAULT_SUMMARY_PROMPT:
        raise RuntimeError(
            "DeepAgents summary prompt contract changed: <messages> marker missing"
        )
    prompt = DEEPAGENTS_DEFAULT_SUMMARY_PROMPT.replace(
        marker, f"\n{contract}\n{marker}", 1
    )
    if "{messages}" not in prompt:
        raise RuntimeError(
            "DeepAgents summary prompt contract changed: {messages} missing"
        )
    return prompt


def create_context_compaction_middleware(
    *,
    model,
    backend,
    settings: ContextCompactionSettings = DEFAULT_CONTEXT_COMPACTION_SETTINGS,
) -> SummarizationMiddleware:
    """创建会替换 DeepAgents 默认摘要器的领域中间件。"""

    settings.validate()
    return SummarizationMiddleware(
        model=model,
        backend=backend,
        trigger=("tokens", settings.trigger_tokens),
        keep=("tokens", settings.keep_tokens),
        summary_prompt=build_procurement_summary_prompt(settings.schema_version),
        # 构造器默认只取旧历史末尾约 4K tokens；这里必须关闭裁剪，否则第一次
        # 压缩可能漏掉早期订单号、审批状态和用户约束。
        trim_tokens_to_summarize=None,
    )
