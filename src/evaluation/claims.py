"""Business-claim extraction used before deterministic ERP fact comparison.

The LLM is allowed to extract statements, but it never scores them. Correctness
is decided only by :class:`EvaluationOracle` against the case's ERP-backed fact
catalog. Optional facts (``required=false``) make valid extra statements
recognisable without increasing required-fact recall.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .models import ActualClaim, EvaluationCase, ToolCallObservation


def _catalog_facts(case: EvaluationCase):
    business = case.expected.business
    if business is None:
        return case.expected.facts
    by_key = {
        fact.key: fact
        for fact in [*business.facts, *business.feasibility_facts]
    }
    return list(by_key.values())


def _catalog_keys(case: EvaluationCase) -> list[str]:
    keys = {fact.key for fact in _catalog_facts(case)}
    if case.expected.safety is not None:
        keys.update(case.expected.safety.forbidden_claim_keys)
    return sorted(keys)


class ClaimExtractor(Protocol):
    async def extract(
        self,
        case: EvaluationCase,
        answer: str,
        tool_calls: list[ToolCallObservation],
    ) -> list[ActualClaim]: ...


def _text_forms(value: object) -> list[str]:
    if isinstance(value, bool):
        return ["true" if value else "false", "是" if value else "否"]
    if isinstance(value, (list, dict)):
        return [json.dumps(value, ensure_ascii=False, sort_keys=True)]
    return [str(value)]


class CatalogClaimExtractor:
    """Network-free extractor for PR smoke tests and tightly structured answers.

    It recognises catalogued facts only. Full hidden evaluation should use
    :class:`LLMClaimExtractor` so unexpected claims are also extracted and can
    reduce precision.
    """

    async def extract(
        self,
        case: EvaluationCase,
        answer: str,
        tool_calls: list[ToolCallObservation],
    ) -> list[ActualClaim]:
        folded = answer.casefold()
        claims: list[ActualClaim] = []
        for fact in _catalog_facts(case):
            forms = [*fact.aliases, *_text_forms(fact.value)]
            matched = next(
                (form for form in forms if form and form.casefold() in folded), None
            )
            if matched is not None:
                claims.append(
                    ActualClaim(
                        key=fact.key,
                        value=fact.value,
                        text=matched,
                        evidence="catalog-text-match",
                    )
                )
        return claims


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    value: Any
    text: str = ""


class ExtractedClaimBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ExtractedClaim] = Field(default_factory=list)


class LLMClaimExtractor:
    """Extract claims with a structured model; never ask the model to score."""

    def __init__(self, model=None):
        if model is None:
            from ..agent.config import get_llm

            model = get_llm(thinking=False, max_retries=1, max_tokens=2048)
        self._model = model.with_structured_output(ExtractedClaimBatch)

    async def extract(
        self,
        case: EvaluationCase,
        answer: str,
        tool_calls: list[ToolCallObservation],
    ) -> list[ActualClaim]:
        # Only expose field names. Reference values and tool results would let the
        # extractor silently "correct" an answer before the deterministic oracle
        # sees it, which would inflate both recall and precision.
        catalog = _catalog_keys(case)
        tool_names = [call.name for call in tool_calls]
        prompt = (
            "你是业务声明抽取器，不是评分器。提取回答中的所有可验证ERP/采购业务声明。"
            "能映射到事实目录时使用目录key；目录之外的声明使用unsupported.1、"
            "unsupported.2等key。value保留回答实际声称的值，不要根据参考值纠正。"
            "寒暄、建议和纯解释不要作为业务声明。\n"
            f"事实字段目录（不含金标值）：{json.dumps(catalog, ensure_ascii=False)}\n"
            f"本次调用过的工具名：{json.dumps(tool_names, ensure_ascii=False)}\n"
            f"Agent回答：{answer}"
        )
        batch = await self._model.ainvoke(prompt)
        if not isinstance(batch, ExtractedClaimBatch):
            batch = ExtractedClaimBatch.model_validate(batch)
        return [
            ActualClaim(
                key=claim.key,
                value=claim.value,
                text=claim.text,
                evidence="llm-extracted; correctness checked by deterministic oracle",
            )
            for claim in batch.claims
        ]
