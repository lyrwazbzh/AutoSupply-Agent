"""统一检索编排：多路召回 → RRF → 粗筛 → 精排/降级 → 精确置顶。

对齐 Smart-Repair retrieval_flow 能力边界（采购域）：
- exact（物料号/供应商代码）+ BM25 + vector → RRF
- 向量路不可用 → BM25+exact 降级，粗筛跳过向量分阈值
- Reranker 不可用 → weighted_rerank 规则精排
- 精确命中置顶后取 FINAL_TOP_N
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from . import settings
from .bm25 import get_bm25_index
from .embeddings import cosine, encode_text, encode_texts
from .reranker import rerank_or_fallback
from .retrieve import _doc_hit, exact_retrieve, rrf_merge
from .store import KnowledgeStore, get_default_store

logger = logging.getLogger(__name__)


def _extract_codes(query: str) -> list[str]:
    codes = re.findall(r"\b(?:P-[A-Z]{2}-\d{4}|SUP\d{4})\b", query or "", re.I)
    return [c.upper() for c in codes]


def bm25_retrieve(
    store: KnowledgeStore,
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: int = 12,
) -> list[dict]:
    pool = store.filter(domain=domain) if domain else store.all()
    index = get_bm25_index(pool)
    hits = []
    for doc, score in index.search(query, top_k=top_k):
        hits.append(_doc_hit(doc, float(score), "bm25"))
    return hits


def vector_retrieve_v2(
    store: KnowledgeStore,
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: int = 12,
) -> tuple[list[dict], str, bool]:
    """返回 (hits, backend, ok)。ok=False 表示向量路整体失败（应触发 BM25-only 降级标记）。"""
    pool = store.filter(domain=domain) if domain else store.all()
    if not pool:
        return [], "empty", True
    try:
        q_vec, backend = encode_text(query)
        if not q_vec:
            return [], backend, False
        vector_search = getattr(store, "vector_search", None)
        if callable(vector_search):
            rows = vector_search(q_vec, domain=domain, top_k=top_k)
            hits = [
                _doc_hit(doc, score, "vector")
                for doc, score, _stored_backend in rows
                if score >= 0.02
            ]
            stored_backends = {item[2] for item in rows if item[2]}
            backend_name = (
                f"pgvector:{next(iter(stored_backends))}"
                if len(stored_backends) == 1
                else "pgvector"
            )
            return hits, backend_name, True
        texts = [f"{d.title}\n{d.content}" for d in pool]
        doc_vecs, doc_backend = encode_texts(texts)
        backend = doc_backend or backend
        scored: list[tuple[int, float]] = []
        for i, dv in enumerate(doc_vecs):
            s = cosine(q_vec, dv)
            if s >= 0.02:
                scored.append((i, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        hits = [_doc_hit(pool[i], s, "vector") for i, s in scored[:top_k]]
        return hits, backend, True
    except Exception as e:
        logger.warning("向量路失败: %s", e)
        return [], "error", False


def _sort_key(m: dict) -> float:
    if m.get("rerank_score") is not None:
        return float(m["rerank_score"])
    if float(m.get("score") or 0) > 0:
        return float(m["score"])
    return float(m.get("rrf_score") or 0)


def filter_rerank(
    merged: list[dict],
    query: str,
    *,
    top_n: Optional[int] = None,
    codes: Optional[list[str]] = None,
    bm25_only: bool = False,
) -> tuple[list[dict], str]:
    """粗筛 → 精排 → 精确置顶 → 截断。返回 (hits, rerank_mode)。"""
    top_n = top_n or settings.FINAL_TOP_N
    codes = codes or _extract_codes(query)

    if bm25_only:
        coarse = sorted(merged, key=lambda x: x.get("rrf_score", 0), reverse=True)
        logger.warning("BM25-only 降级：跳过向量分粗筛阈值")
    else:
        thr = settings.COARSE_THRESHOLD
        coarse = [
            m
            for m in merged
            if m.get("method") == "exact"
            or m.get("rrf_only")
            or float(m.get("score") or 0) >= thr
            or float(m.get("rrf_score") or 0) >= thr * 0.5
        ]
        if not coarse and merged:
            # 阈值过严时保留 RRF 头部，避免全灭
            coarse = sorted(merged, key=lambda x: x.get("rrf_score", 0), reverse=True)[
                : settings.RERANKER_CANDIDATES
            ]

    if not coarse:
        return [], "empty"

    ranked, mode = rerank_or_fallback(query, coarse)
    ranked.sort(key=_sort_key, reverse=True)

    # 精确编码 / exact method 置顶
    if codes:
        ranked.sort(
            key=lambda x: (
                0
                if (
                    x.get("method") == "exact"
                    or any(
                        c in [p.upper() for p in (x.get("part_codes") or [])]
                        or c in [s.upper() for s in (x.get("supplier_codes") or [])]
                        for c in codes
                    )
                )
                else 1,
                -_sort_key(x),
            )
        )
    elif any(x.get("method") == "exact" for x in ranked):
        ranked.sort(
            key=lambda x: (0 if x.get("method") == "exact" else 1, -_sort_key(x))
        )

    if bm25_only:
        return ranked[:top_n], mode

    thr = settings.COARSE_THRESHOLD
    kept = [
        m
        for m in ranked
        if m.get("method") == "exact" or _sort_key(m) >= thr * 0.5
    ]
    return (kept or ranked)[:top_n], mode


def retrieve_hybrid(
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: Optional[int] = None,
    store: Optional[KnowledgeStore] = None,
    enable_vector: bool = True,
    enable_rerank: bool = True,
) -> dict[str, Any]:
    """统一入口：多路 → RRF → 粗筛精排。"""
    store = store or get_default_store()
    recall_k = top_k or settings.RECALL_TOP_K
    final_n = min(recall_k, settings.FINAL_TOP_N) if top_k else settings.FINAL_TOP_N
    # 调用方传 top_k 时作为最终条数；召回仍用 RECALL_TOP_K
    if top_k is not None:
        final_n = max(1, min(int(top_k), 10))
        recall_k = max(final_n, settings.RECALL_TOP_K)

    methods: list[str] = []
    lanes: list[list[dict]] = []
    codes = _extract_codes(query)
    vector_ok = True
    embed_backend = "off"
    degraded = False

    exact = exact_retrieve(store, query, domain=domain, top_k=recall_k)
    if exact:
        lanes.append(exact)
        methods.append("exact")

    bm25 = bm25_retrieve(store, query, domain=domain, top_k=recall_k)
    if bm25:
        lanes.append(bm25)
        methods.append("bm25")

    if enable_vector:
        vec, embed_backend, vector_ok = vector_retrieve_v2(
            store, query, domain=domain, top_k=recall_k
        )
        if vec:
            lanes.append(vec)
            methods.append("vector")
        if not vector_ok:
            degraded = True
            logger.warning("向量路不可用，检索降级为 BM25+exact")
            # 标记 rrf_only：无向量分可依
            for lane in lanes:
                for item in lane:
                    item["rrf_only"] = True

    if not lanes:
        return {
            "query": query,
            "domain": domain,
            "methods": methods,
            "degraded": True,
            "embed_backend": embed_backend,
            "rerank_mode": "skip",
            "codes": codes,
            "hits": [],
        }

    merged = rrf_merge(lanes, k=settings.RRF_K, top_n=recall_k)
    bm25_only = degraded or ("vector" not in methods and enable_vector is False)

    if enable_rerank:
        hits, rerank_mode = filter_rerank(
            merged, query, top_n=final_n, codes=codes, bm25_only=bm25_only or degraded
        )
    else:
        hits, rerank_mode = merged[:final_n], "off"

    for h in hits:
        content = h.get("content") or ""
        if len(content) > 600:
            h["content"] = content[:600] + "…"

    return {
        "query": query,
        "domain": domain,
        "methods": methods,
        "degraded": degraded,
        "embed_backend": embed_backend,
        "rerank_mode": rerank_mode,
        "codes": codes,
        "hits": hits,
    }


def evaluate_retrieval_quality(results: list[dict]) -> dict[str, Any]:
    """检索质量阀门（规则，零 LLM）。"""
    if not results:
        return {"sufficient": False, "reason": "无结果", "count": 0, "max_score": 0.0}
    scores = [_sort_key(r) for r in results]
    max_score = max(scores) if scores else 0.0
    high = sum(1 for s in scores if s >= 0.6)
    if len(results) >= 2 and (high >= 1 or max_score >= 0.4):
        return {
            "sufficient": True,
            "reason": f"结果充足 ({len(results)} 条, 最高分 {max_score:.2f})",
            "count": len(results),
            "max_score": round(max_score, 4),
        }
    if len(results) >= 1 and max_score >= 0.25:
        return {
            "sufficient": True,
            "reason": f"弱相关可用 ({len(results)} 条, 最高分 {max_score:.2f})",
            "count": len(results),
            "max_score": round(max_score, 4),
        }
    return {
        "sufficient": False,
        "reason": f"结果不足 ({len(results)} 条, 最高分 {max_score:.2f})",
        "count": len(results),
        "max_score": round(max_score, 4),
    }
