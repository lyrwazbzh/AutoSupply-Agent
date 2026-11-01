"""有界 ReAct 补搜：证据不足时改写查询并限轮次重检（白名单工具语义，禁止写 ERP）。"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .evidence import BOUNDED_REACT_POLICY, assess_evidence
from .retrieval_flow import retrieve_hybrid
from .store import KnowledgeStore, get_default_store

logger = logging.getLogger(__name__)

_SYNONYM_EXPAND = [
    (r"准入|信用|AVL", "供应商准入 信用等级 AVL"),
    (r"SOP|作业|审批", "缺料补货采购 SOP 审批"),
    (r"规格|技术规格", "技术规格 零件编码"),
    (r"延期|交期|异常", "供应商交付延期 异常处置"),
    (r"制动", "制动片 P-BR-0001"),
    (r"火花塞", "火花塞 P-EN-0001"),
    (r"曲轴", "曲轴 P-EN-0004"),
]


def rewrite_query(query: str, round_idx: int, prev_hits: list[dict]) -> str:
    """确定性改写：第 0 轮扩同义词；第 1 轮抽编码/域名再搜。"""
    q = (query or "").strip()
    codes = re.findall(r"\b(?:P-[A-Z]{2}-\d{4}|SUP\d{4})\b", q, re.I)
    if round_idx == 0:
        extras = []
        for pat, expand in _SYNONYM_EXPAND:
            if re.search(pat, q, re.I):
                extras.append(expand)
        if extras:
            return f"{q} {' '.join(extras)}"
        return f"{q} 采购 制度 规格"
    # round >= 1：编码优先；否则用上一轮 top title 词
    if codes:
        return " ".join(c.upper() for c in codes)
    titles = " ".join((h.get("title") or "")[:40] for h in (prev_hits or [])[:2])
    return f"{q} {titles}".strip() or q


def _merge_hits(pools: list[list[dict]], limit: int = 8) -> list[dict]:
    seen: dict[str, dict] = {}
    order: list[str] = []
    for pool in pools:
        for h in pool:
            key = str(h.get("_dedup_key") or h.get("id") or "")
            if not key:
                continue
            if key not in seen:
                seen[key] = dict(h)
                order.append(key)
            else:
                # 保留更高精排/相关分
                prev = seen[key]
                def _s(x: dict) -> float:
                    return float(
                        x.get("rerank_score")
                        or x.get("score")
                        or x.get("rrf_score")
                        or 0
                    )

                if _s(h) > _s(prev):
                    seen[key] = dict(h)
    return [seen[k] for k in order[:limit]]


def bounded_retrieve(
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: int = 5,
    store: Optional[KnowledgeStore] = None,
    max_rounds: Optional[int] = None,
) -> dict[str, Any]:
    """pipeline-first → assess_evidence → 不足则有界补搜。

    返回结构兼容 hybrid_retrieve，并附加:
      react_rounds / react_queries / evidence_assessment / bounded_react_policy
    """
    store = store or get_default_store()
    policy = BOUNDED_REACT_POLICY
    rounds_budget = max_rounds if max_rounds is not None else int(policy.get("max_rounds", 2))

    first = retrieve_hybrid(
        query, domain=domain, top_k=top_k, store=store, enable_vector=True, enable_rerank=True
    )
    assessment = assess_evidence(first)
    react_rounds: list[dict] = []
    queries = [query]
    pools = [first.get("hits") or []]

    if assessment.sufficient:
        return {
            **first,
            "evidence_assessment": assessment.to_dict(),
            "react_rounds": [],
            "react_queries": queries,
            "bounded_react_policy": None,
            "rag_react_mode": False,
        }

    logger.info("evidence 不足，启动有界 ReAct 补搜（max_rounds=%s）", rounds_budget)
    current_hits = list(pools[0])
    for i in range(rounds_budget):
        q2 = rewrite_query(query, i, current_hits)
        queries.append(q2)
        # 第 1 轮起若有编码，可不限 domain 扩大召回
        dom = domain if i == 0 else None
        nxt = retrieve_hybrid(
            q2, domain=dom, top_k=top_k, store=store, enable_vector=True, enable_rerank=True
        )
        pools.append(nxt.get("hits") or [])
        current_hits = _merge_hits(pools, limit=max(top_k, 8))
        trial = {**first, "hits": current_hits, "methods": list(
            dict.fromkeys((first.get("methods") or []) + (nxt.get("methods") or []) + ["react"])
        )}
        assessment = assess_evidence(trial)
        react_rounds.append(
            {
                "round": i + 1,
                "query": q2,
                "hit_count": len(nxt.get("hits") or []),
                "merged_count": len(current_hits),
                "sufficient": assessment.sufficient,
                "reason": assessment.reason,
            }
        )
        if assessment.sufficient:
            first = trial
            break
        first = trial

    first["hits"] = current_hits[:top_k]
    first["degraded"] = bool(first.get("degraded")) or True
    return {
        **first,
        "evidence_assessment": assessment.to_dict(),
        "react_rounds": react_rounds,
        "react_queries": queries,
        "bounded_react_policy": policy,
        "rag_react_mode": False,  # 补搜已在工具内完成，外层无需再开写禁
    }


def run_bounded_search_tool(
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: int = 5,
    auto_rescue: bool = True,
) -> dict[str, Any]:
    """供 search_business_knowledge 调用。"""
    if auto_rescue:
        return bounded_retrieve(query, domain=domain, top_k=top_k)
    result = retrieve_hybrid(query, domain=domain, top_k=top_k)
    assessment = assess_evidence(result)
    return {
        **result,
        "evidence_assessment": assessment.to_dict(),
        "react_rounds": [],
        "react_queries": [query],
        "bounded_react_policy": BOUNDED_REACT_POLICY if assessment.suggest_react else None,
        "rag_react_mode": False,
    }
