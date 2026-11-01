"""混合检索：精确标识 + 关键词加权 + 轻量向量，RRF 融合。"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Optional

from .store import KnowledgeDoc, KnowledgeStore, tokenize


def rrf_merge(result_sets: list[list[dict]], k: int = 60, top_n: int = 8) -> list[dict]:
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}
    for result_set in result_sets:
        for rank, item in enumerate(result_set, start=1):
            item_id = str(item.get("_dedup_key") or item.get("id") or "")
            if not item_id:
                continue
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            prev = payloads.get(item_id)
            if prev is None or float(item.get("score") or 0) > float(prev.get("score") or 0):
                payloads[item_id] = dict(item)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    out: list[dict] = []
    for item_id, rrf in ranked:
        row = payloads[item_id]
        row["rrf_score"] = round(rrf, 6)
        out.append(row)
    return out


def _doc_hit(doc: KnowledgeDoc, score: float, method: str) -> dict[str, Any]:
    return {
        "id": doc.id,
        "_dedup_key": f"K:{doc.id}",
        "title": doc.title,
        "content": doc.content,
        "domain": doc.domain,
        "source": doc.source,
        "version": doc.version,
        "score": round(score, 4),
        "method": method,
        "part_codes": doc.part_codes,
        "supplier_codes": doc.supplier_codes,
    }


def exact_retrieve(
    store: KnowledgeStore,
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """物料号 / 供应商代码 / 文档 id 精确优先。"""
    q = query.strip()
    codes = re.findall(r"\b(?:P-[A-Z]{2}-\d{4}|SUP\d{4}|[A-Z]-?\d{2,4})\b", q, re.I)
    codes = [c.upper() for c in codes]
    hits: list[dict] = []
    pool = store.filter(domain=domain) if domain else store.all()
    for doc in pool:
        score = 0.0
        if q.upper() == doc.id.upper() or q in doc.title:
            score += 2.0
        for c in codes:
            if c in [x.upper() for x in doc.part_codes]:
                score += 3.0
            if c in [x.upper() for x in doc.supplier_codes]:
                score += 3.0
            if c in doc.content.upper():
                score += 1.0
        if score > 0:
            hits.append(_doc_hit(doc, score, "exact"))
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]


def keyword_retrieve(
    store: KnowledgeStore,
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: int = 8,
) -> list[dict]:
    """加权关键词召回（标题权重高于正文；对外称关键词加权，非标准 BM25）。"""
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    q_set = set(q_tokens)
    hits: list[dict] = []
    pool = store.filter(domain=domain) if domain else store.all()
    for doc in pool:
        title_t = tokenize(doc.title)
        body_t = tokenize(doc.content)
        title_hit = sum(1 for t in title_t if t in q_set)
        body_hit = sum(1 for t in body_t if t in q_set)
        if title_hit == 0 and body_hit == 0:
            continue
        score = title_hit * 2.5 + body_hit * 1.0
        # 长度归一
        score = score / math.sqrt(max(len(body_t), 1))
        hits.append(_doc_hit(doc, score, "keyword"))
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]


def _bow_vector(tokens: list[str]) -> Counter:
    return Counter(tokens)


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b[t] for t in a if t in b)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def vector_retrieve(
    store: KnowledgeStore,
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: int = 8,
) -> list[dict]:
    """轻量词袋向量语义召回（无外部 embedding 服务时的可运行实现）。"""
    qv = _bow_vector(tokenize(query))
    if not qv:
        return []
    hits: list[dict] = []
    pool = store.filter(domain=domain) if domain else store.all()
    for doc in pool:
        dv = _bow_vector(tokenize(doc.title + " " + doc.content))
        score = _cosine(qv, dv)
        if score >= 0.05:
            hits.append(_doc_hit(doc, score, "vector"))
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]


def hybrid_retrieve(
    query: str,
    *,
    domain: Optional[str] = None,
    top_k: int = 5,
    store: Optional[KnowledgeStore] = None,
    enable_vector: bool = True,
    enable_rerank: bool = True,
) -> dict[str, Any]:
    """统一入口委托 retrieval_flow：exact + BM25 + vector → RRF → 粗筛精排。"""
    from .retrieval_flow import retrieve_hybrid as _flow

    return _flow(
        query,
        domain=domain,
        top_k=top_k,
        store=store,
        enable_vector=enable_vector,
        enable_rerank=enable_rerank,
    )
