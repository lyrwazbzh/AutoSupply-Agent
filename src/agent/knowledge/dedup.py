"""入库前去重：source+title 精确键 + 编码交集 + 向量相似（可选 LLM 粗判省略，保守不误杀）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .embeddings import cosine, encode_text
from .store import KnowledgeDoc, KnowledgeStore


@dataclass
class DedupDecision:
    is_duplicate: bool
    reason: str
    matched_id: Optional[str] = None
    score: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _code_overlap(a: KnowledgeDoc, part_codes: list[str], supplier_codes: list[str]) -> int:
    parts = {c.upper() for c in (a.part_codes or [])}
    sups = {c.upper() for c in (a.supplier_codes or [])}
    return len(parts & {c.upper() for c in part_codes}) + len(
        sups & {c.upper() for c in supplier_codes}
    )


def check_duplicate(
    *,
    title: str,
    content: str,
    source: str,
    domain: str,
    part_codes: Optional[list[str]] = None,
    supplier_codes: Optional[list[str]] = None,
    store: Optional[KnowledgeStore] = None,
    exact_id: Optional[str] = None,
    vector_threshold: float = 0.82,
) -> DedupDecision:
    """判定是否真重复。

    - 同 source+title（exact_id 已存在）→ 覆盖型重复（调用方可 overwrite）
    - 同 domain 且编码交集≥1 且标题高度重合 → 重复
    - 向量余弦 ≥ threshold → 重复候选
    """
    from .store import get_default_store

    store = store or get_default_store()
    part_codes = part_codes or []
    supplier_codes = supplier_codes or []
    candidates: list[dict[str, Any]] = []

    if exact_id and store.get(exact_id):
        return DedupDecision(
            is_duplicate=True,
            reason="same_source_title",
            matched_id=exact_id,
            score=1.0,
            candidates=[{"id": exact_id, "via": "exact_key"}],
        )

    title_n = (title or "").strip().lower()
    pool = [d for d in store.all() if d.domain == domain] or store.all()

    # 编码 + 标题子串
    for doc in pool:
        overlap = _code_overlap(doc, part_codes, supplier_codes)
        title_hit = title_n and (
            title_n in (doc.title or "").lower() or (doc.title or "").lower() in title_n
        )
        if overlap >= 1 and title_hit:
            return DedupDecision(
                is_duplicate=True,
                reason="code_and_title",
                matched_id=doc.id,
                score=0.95,
                candidates=[{"id": doc.id, "via": "code_title", "overlap": overlap}],
            )
        if overlap >= 2:
            candidates.append({"id": doc.id, "via": "codes", "overlap": overlap})

    # 向量相似
    try:
        q_vec, _ = encode_text(f"{title}\n{content[:800]}")
        best_id = None
        best = 0.0
        for doc in pool:
            d_vec, _ = encode_text(f"{doc.title}\n{(doc.content or '')[:800]}")
            s = cosine(q_vec, d_vec)
            if s >= vector_threshold * 0.9:
                candidates.append({"id": doc.id, "via": "vector", "score": round(s, 4)})
            if s > best:
                best, best_id = s, doc.id
        if best_id and best >= vector_threshold:
            return DedupDecision(
                is_duplicate=True,
                reason="vector_similarity",
                matched_id=best_id,
                score=round(best, 4),
                candidates=candidates[:5],
            )
    except Exception:
        pass

    return DedupDecision(
        is_duplicate=False,
        reason="unique",
        matched_id=None,
        score=0.0,
        candidates=candidates[:5],
    )
