"""COLD 层检索融合打分。

召回在 ``postgres_search.recall_ranked_lanes``（有效性 → BM25 Top-k / 向量 Top-k）；
本模块：两路 RRF → max 归一化 → combined_score（时间/频次/置信度）。
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import List, Optional, Sequence

from .embeddings import cosine

_PUNCT_RE = re.compile(r"^[\W_]+$", re.UNICODE)


def tokenize(text: str) -> List[str]:
    """BM25 分词：jieba 中英混切，小写，丢掉纯标点空白。"""
    raw = (text or "").strip().lower()
    if not raw:
        return []
    import jieba

    tokens: List[str] = []
    for piece in jieba.lcut(raw, cut_all=False):
        tok = (piece or "").strip()
        if not tok or _PUNCT_RE.match(tok):
            continue
        tokens.append(tok)
    return tokens


def bm25(query_tokens: Sequence[str], docs: Sequence[Sequence[str]],
         k1: float = 1.5, b: float = 0.75) -> List[float]:
    """标准 BM25，返回每条 doc 的原始分（未归一化）。"""
    n_docs = len(docs)
    if n_docs == 0:
        return []
    df: dict = {}
    lengths: List[int] = []
    for tokens in docs:
        lengths.append(len(tokens))
        for term in set(tokens):
            df[term] = df.get(term, 0) + 1
    avgdl = (sum(lengths) / n_docs) or 1.0

    scores: List[float] = []
    for tokens, dl in zip(docs, lengths):
        if not tokens:
            scores.append(0.0)
            continue
        tf: dict = {}
        for term in tokens:
            tf[term] = tf.get(term, 0) + 1
        total = 0.0
        for term in set(query_tokens):
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n_docs - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            denom = freq + k1 * (1 - b + b * (dl / avgdl))
            total += idf * (freq * (k1 + 1)) / denom
        scores.append(total)
    return scores


def normalize(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    top = max(values)
    if top <= 0:
        return [0.0] * len(values)
    return [v / top for v in values]


def recency_score(age_days: float, half_life_days: float = 30.0) -> float:
    """指数衰减：半衰期默认 30 天。"""
    if half_life_days <= 0:
        return 1.0
    return math.pow(0.5, max(0.0, age_days) / half_life_days)


def access_score(access_count: int, cap: int = 10) -> float:
    if access_count <= 0:
        return 0.0
    return min(1.0, access_count / float(cap))


def combined_score(
    text_score: float,
    age_days: float,
    access_count: int,
    confidence: float,
    *,
    half_life_days: float = 30.0,
    weight_text: float = 0.6,
    weight_recency: float = 0.2,
    weight_access: float = 0.1,
    weight_confidence: float = 0.1,
) -> float:
    return (
        weight_text * max(0.0, min(1.0, text_score))
        + weight_recency * recency_score(age_days, half_life_days)
        + weight_access * access_score(access_count)
        + weight_confidence * max(0.0, min(1.0, confidence))
    )


def rrf_merge(
    result_sets: list[list[dict]],
    k: int = 60,
    top_n: int = 8,
    *,
    id_keys: tuple[str, ...] = ("_dedup_key", "id"),
) -> list[dict]:
    """多路有序列表的 Reciprocal Rank Fusion；知识检索与记忆 COLD 共用。"""
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    def _item_id(item: dict) -> str:
        for key in id_keys:
            value = item.get(key)
            if value:
                return str(value)
        return ""

    for result_set in result_sets:
        for rank_idx, item in enumerate(result_set, start=1):
            item_id = _item_id(item)
            if not item_id:
                continue
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank_idx)
            prev = payloads.get(item_id)
            if prev is None or float(item.get("score") or 0) > float(prev.get("score") or 0):
                payloads[item_id] = dict(item)
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)[:top_n]
    out: list[dict] = []
    for item_id, rrf in ranked:
        row = payloads[item_id]
        row["rrf_score"] = round(rrf, 6)
        out.append(row)
    return out


def rank_from_lanes(
    keyword_lane: Sequence,
    vector_lane: Sequence,
    config=None,
    now: Optional[datetime] = None,
    *,
    rrf_k: int = 60,
    top_n: Optional[int] = None,
):
    """对已排好序的关键词路 / 向量路做 RRF → 归一化 → combined_score。"""
    from .config import DEFAULT_MEMORY_CONFIG

    cfg = config or DEFAULT_MEMORY_CONFIG
    kw = list(keyword_lane or [])
    vec = list(vector_lane or [])
    if not kw and not vec:
        return []

    by_id = {}
    for item in kw + vec:
        by_id[str(item.id)] = item

    lanes = []
    if kw:
        lanes.append(
            [
                {"id": item.id, "score": float(len(kw) - idx)}
                for idx, item in enumerate(kw)
            ]
        )
    if vec:
        lanes.append(
            [
                {"id": item.id, "score": float(len(vec) - idx)}
                for idx, item in enumerate(vec)
            ]
        )

    merge_n = top_n if top_n is not None else len(by_id)
    merged = rrf_merge(lanes, k=rrf_k, top_n=max(1, merge_n))
    channels = normalize([float(row.get("rrf_score") or 0.0) for row in merged])

    now_dt = now or datetime.now()
    scored = []
    for row, channel in zip(merged, channels):
        item = by_id.get(str(row.get("id") or ""))
        if item is None:
            continue
        score = combined_score(
            channel,
            item.age_days(now_dt),
            item.access_count,
            item.confidence,
            half_life_days=cfg.half_life_days,
            weight_text=cfg.weight_text,
            weight_recency=cfg.weight_recency,
            weight_access=cfg.weight_access,
            weight_confidence=cfg.weight_confidence,
        )
        scored.append((item, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def rank(
    query: str,
    candidates: Sequence,
    config=None,
    now: Optional[datetime] = None,
    *,
    query_embedding: Optional[Sequence[float]] = None,
    rrf_k: int = 60,
):
    """兼容入口：在候选集上本地拆 BM25 / 余弦两路后再 ``rank_from_lanes``。

    主检索路径请用 ``recall_ranked_lanes`` + ``rank_from_lanes``，避免 PG 召回后再整池重算。
    """
    if not candidates:
        return []
    from .config import DEFAULT_MEMORY_CONFIG

    cfg = config or DEFAULT_MEMORY_CONFIG
    query_tokens = tokenize(query)
    has_query_tokens = bool(query_tokens)
    has_query_vec = bool(query_embedding)
    if not has_query_tokens and not has_query_vec:
        return []

    docs = [tokenize(item.searchable_text()) for item in candidates]
    raw = bm25(query_tokens, docs) if has_query_tokens else [0.0] * len(candidates)
    min_cosine = float(getattr(cfg, "min_cosine", 0.32))

    keyword_ranked = [
        item
        for item, score in sorted(
            ((item, float(score)) for item, score in zip(candidates, raw) if score > 0),
            key=lambda row: row[1],
            reverse=True,
        )
    ]
    vector_ranked: list = []
    if has_query_vec:
        scored_vec = []
        for item in candidates:
            semantic_score = cosine(query_embedding, getattr(item, "embedding", None))
            if semantic_score >= min_cosine:
                scored_vec.append((item, float(semantic_score)))
        scored_vec.sort(key=lambda row: row[1], reverse=True)
        vector_ranked = [item for item, _ in scored_vec]

    return rank_from_lanes(
        keyword_ranked,
        vector_ranked,
        cfg,
        now,
        rrf_k=rrf_k,
        top_n=len(candidates),
    )
