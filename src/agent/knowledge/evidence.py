"""检索证据充分性评估：充分则直接用；不足则建议有界补检。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvidenceAssessment:
    sufficient: bool
    reason: str
    hit_count: int = 0
    max_rrf: float = 0.0
    suggest_react: bool = False
    missing_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_evidence(
    retrieve_result: dict[str, Any],
    *,
    min_hits: int = 1,
    min_rrf: float = 0.01,
    require_source: bool = True,
) -> EvidenceAssessment:
    hits = retrieve_result.get("hits") or []
    if not hits:
        return EvidenceAssessment(
            sufficient=False,
            reason="无检索命中",
            suggest_react=True,
            missing_hints=["扩大关键词", "指定 domain=procurement_sop|avl|material_spec"],
        )
    try:
        from .retrieval_flow import evaluate_retrieval_quality

        quality = evaluate_retrieval_quality(hits)
        max_rrf = float(quality.get("max_score") or 0)
        if not quality.get("sufficient"):
            return EvidenceAssessment(
                sufficient=False,
                reason=quality.get("reason") or "命中过少或相关分过低",
                hit_count=len(hits),
                max_rrf=max_rrf,
                suggest_react=True,
                missing_hints=["换用物料号/供应商代码精确检索", "有界 ReAct 补检"],
            )
    except Exception:
        max_rrf = max(float(h.get("rrf_score") or h.get("score") or 0) for h in hits)
        if len(hits) < min_hits or max_rrf < min_rrf:
            return EvidenceAssessment(
                sufficient=False,
                reason="命中过少或相关分过低",
                hit_count=len(hits),
                max_rrf=max_rrf,
                suggest_react=True,
                missing_hints=["换用物料号/供应商代码精确检索", "有界 ReAct 补检"],
            )
    else:
        if len(hits) < min_hits:
            return EvidenceAssessment(
                sufficient=False,
                reason="命中过少",
                hit_count=len(hits),
                max_rrf=max_rrf,
                suggest_react=True,
                missing_hints=["换用物料号/供应商代码精确检索", "有界 ReAct 补检"],
            )
    if require_source and not any(h.get("source") for h in hits):
        return EvidenceAssessment(
            sufficient=False,
            reason="命中缺少来源字段",
            hit_count=len(hits),
            max_rrf=max_rrf,
            suggest_react=False,
        )
    return EvidenceAssessment(
        sufficient=True,
        reason="证据充分",
        hit_count=len(hits),
        max_rrf=max_rrf,
        suggest_react=False,
    )


BOUNDED_REACT_POLICY = {
    "max_rounds": 2,
    "allowed_tools": ["search_business_knowledge", "part_query", "supplier_search"],
    "forbid_write": True,
}
