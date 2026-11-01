"""精排：HTTP Reranker 优先；不可用时规则 weighted_rerank（采购域）。"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

from . import settings
from .store import tokenize

logger = logging.getLogger(__name__)


def is_reranker_available() -> bool:
    url = settings.RERANKER_SERVER_URL
    if not url or not settings.RERANKER_ENABLED:
        return False
    try:
        r = httpx.get(f"{url}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def http_rerank(query: str, docs: list[dict], top_n: Optional[int] = None) -> Optional[list[dict]]:
    """调用 /v1/rerank；失败返回 None 由调用方降级。"""
    if not docs or not is_reranker_available():
        return None
    url = settings.RERANKER_SERVER_URL
    payload = {
        "model": settings.RERANKER_MODEL,
        "query": query,
        "documents": [
            f"{d.get('title', '')}\n{d.get('content', '')}" for d in docs
        ],
        "top_n": top_n or len(docs),
    }
    try:
        r = httpx.post(f"{url}/v1/rerank", json=payload, timeout=settings.HTTP_TIMEOUT)
        r.raise_for_status()
        results = r.json().get("results") or r.json().get("data") or []
        # OpenAI-ish: [{index, relevance_score}]
        scored = []
        for row in results:
            idx = int(row.get("index", row.get("idx", -1)))
            if idx < 0 or idx >= len(docs):
                continue
            item = dict(docs[idx])
            item["rerank_score"] = float(row.get("relevance_score", row.get("score", 0)))
            scored.append(item)
        scored.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return scored
    except Exception as e:
        logger.warning("Reranker HTTP 失败: %s", e)
        return None


def weighted_rerank(results: list[dict], query: str) -> list[dict]:
    """规则精排：业务词命中加分；domain/编码精确命中置顶倾向。"""
    if not results:
        return results
    q_tokens = set(tokenize(query))
    codes = set(re.findall(r"\b(?:P-[A-Z]{2}-\d{4}|SUP\d{4})\b", query, re.I))
    codes = {c.upper() for c in codes}
    domain_hints = {
        "准入": "avl",
        "信用": "avl",
        "SOP": "procurement_sop",
        "作业": "procurement_sop",
        "规格": "material_spec",
        "异常": "exception",
        "延期": "exception",
    }
    prefer_domain = None
    for kw, dom in domain_hints.items():
        if kw.lower() in query.lower() or kw in query:
            prefer_domain = dom
            break

    out = []
    for item in results:
        base = float(
            item.get("rerank_score")
            or item.get("score")
            or item.get("rrf_score")
            or 0
        )
        title = item.get("title") or ""
        content = item.get("content") or ""
        blob = f"{title} {content}".lower()
        hit = sum(1 for t in q_tokens if t.lower() in blob)
        ratio = hit / max(len(q_tokens), 1)
        score = base
        if ratio < 0.2 and item.get("method") != "exact":
            score *= 0.2
        else:
            score += 0.15 * hit
        # 编码精确
        part_codes = [c.upper() for c in (item.get("part_codes") or [])]
        sup_codes = [c.upper() for c in (item.get("supplier_codes") or [])]
        if codes & set(part_codes + sup_codes):
            score += 1.5
        if prefer_domain and item.get("domain") == prefer_domain:
            score += 0.4
        if item.get("method") == "exact":
            score += 0.8
        row = dict(item)
        row["rerank_score"] = round(score, 4)
        out.append(row)
    out.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
    return out


def rerank_or_fallback(query: str, candidates: list[dict]) -> tuple[list[dict], str]:
    """返回 (结果, mode=http|rules)。"""
    if len(candidates) <= 1:
        return candidates, "skip"
    head = candidates[: settings.RERANKER_CANDIDATES]
    tail = candidates[settings.RERANKER_CANDIDATES :]
    ranked = http_rerank(query, head)
    if ranked is not None:
        return ranked + tail, "http"
    logger.warning("Reranker 不可用，回退 weighted_rerank")
    return weighted_rerank(candidates, query), "rules"
