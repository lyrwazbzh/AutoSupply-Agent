"""PostgreSQL 记忆索引与双路召回。

召回口径：有效性过滤 → 关键词 BM25 Top-k → 向量 Top-k；
融合（RRF + 归一化）在 ``scoring.rank_from_lanes``。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional, Sequence

from psycopg.types.json import Jsonb

from ...database import get_pg_pool
from . import namespaces as ns
from .config import MemoryConfig
from .embeddings import encode_text
from .scoring import bm25, tokenize
from .types import MemoryItem, now_iso


def _prefixes(user_id: str) -> tuple[str, str, str]:
    return tuple(".".join(parts) for parts in ns.user_namespaces(user_id))


def _keyword_text(item: MemoryItem) -> str:
    return item.searchable_text()


def _semantic_text(item: MemoryItem) -> str:
    return " ".join(
        part for part in (item.summary, item.content, " ".join(item.entities)) if part
    )


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10g}" for value in vector) + "]"


def _parse_pg_vector(raw: Any) -> Optional[list[float]]:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        try:
            return [float(x) for x in raw]
        except (TypeError, ValueError):
            return None
    text = str(raw).strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            return [float(x) for x in text[1:-1].split(",") if x.strip()]
        except ValueError:
            return None
    return None


def _http_embedding(
    text: str,
    *,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
) -> list[float]:
    vector, backend = encode_text(
        text,
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
    return vector if backend == "http" else []


def index_item(user_id: str, item: MemoryItem, config: MemoryConfig | None = None) -> None:
    """更新现有 Store 行的检索文本；内容未变化时不重复生成向量。"""
    prefix = ".".join(ns.type_ns(user_id, item.type))
    keyword_text = _keyword_text(item)
    semantic_text = _semantic_text(item)
    semantic_hash = hashlib.sha256(semantic_text.encode("utf-8")).hexdigest()
    cfg = config

    pool = get_pg_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT embedding_hash FROM store WHERE prefix = %s AND key = %s",
            (prefix, item.store_key),
        )
        row = cur.fetchone()
        if row is None:
            return
        if row.get("embedding_hash") == semantic_hash:
            cur.execute(
                "UPDATE store SET search_text = %s WHERE prefix = %s AND key = %s",
                (keyword_text, prefix, item.store_key),
            )
            return

    vector = _http_embedding(
        semantic_text,
        base_url=(cfg.embedding_base_url if cfg else ""),
        api_key=(cfg.embedding_api_key if cfg else ""),
        model=(cfg.embedding_model if cfg else ""),
    )
    if not vector and item.embedding:
        vector = list(item.embedding)
    vector_literal = _vector_literal(vector) if vector else None
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE store
            SET search_text = %s,
                embedding = %s::vector,
                embedding_hash = %s
            WHERE prefix = %s AND key = %s
            """,
            (
                keyword_text,
                vector_literal,
                semantic_hash,
                prefix,
                item.store_key,
            ),
        )


def _keyword_lane(user_id: str, query: str, limit: int) -> list[dict[str, Any]]:
    prefixes = _prefixes(user_id)
    with get_pg_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH keyword_query AS (
                SELECT plainto_tsquery('public.procurement_zh', %s) AS query
            )
            SELECT store.prefix, store.key, store.value, store.embedding,
                   ts_rank_cd(store.search_document, keyword_query.query) AS text_rank
            FROM store, keyword_query
            WHERE store.prefix IN (%s, %s, %s)
              AND coalesce(store.value->>'invalidated_at', '') = ''
              AND store.search_document @@ keyword_query.query
            ORDER BY text_rank DESC, store.updated_at DESC
            LIMIT %s
            """,
            (
                query,
                *prefixes,
                limit,
            ),
        )
        return [dict(row) for row in cur.fetchall()]


def _vector_lane(
    user_id: str,
    query_embedding: Sequence[float],
    limit: int,
    min_score: float,
) -> list[dict[str, Any]]:
    if not query_embedding:
        return []
    literal = _vector_literal(list(query_embedding))
    prefixes = _prefixes(user_id)
    with get_pg_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT prefix, key, value, embedding,
                   1 - (embedding <=> %s::vector) AS vector_score
            FROM store
            WHERE prefix IN (%s, %s, %s)
              AND coalesce(value->>'invalidated_at', '') = ''
              AND embedding IS NOT NULL
              AND vector_dims(embedding) = %s
              AND 1 - (embedding <=> %s::vector) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                literal,
                *prefixes,
                len(query_embedding),
                literal,
                min_score,
                literal,
                limit,
            ),
        )
        return [dict(row) for row in cur.fetchall()]


def _touch_rows(rows: list[tuple[str, str]]) -> None:
    stamp = now_iso()
    with get_pg_pool().connection() as conn, conn.cursor() as cur:
        for prefix, key in rows:
            cur.execute(
                """
                UPDATE store
                SET value = jsonb_set(
                        jsonb_set(
                            value,
                            '{access_count}',
                            to_jsonb(coalesce((value->>'access_count')::integer, 0) + 1),
                            true
                        ),
                        '{last_accessed_at}',
                        %s,
                        true
                    ),
                    updated_at = now()
                WHERE prefix = %s AND key = %s
                """,
                (Jsonb(stamp), prefix, key),
            )


def touch_items(user_id: str, items: list[MemoryItem]) -> None:
    """Record one real retrieval for each selected memory item."""
    rows = {
        (".".join(ns.type_ns(user_id, item.type)), item.store_key)
        for item in items
    }
    if rows:
        _touch_rows(sorted(rows))


def _rows_to_valid_items(
    rows: list[dict[str, Any]],
    now: Optional[datetime],
) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    seen: set[str] = set()
    for row in rows:
        item = MemoryItem.from_dict(row.get("value"))
        if item is None or not item.is_valid(now):
            continue
        if item.id in seen:
            continue
        seen.add(item.id)
        if not item.embedding:
            item.embedding = _parse_pg_vector(row.get("embedding"))
        items.append(item)
    return items


def _bm25_topk(
    query: str,
    items: list[MemoryItem],
    limit: int,
) -> list[MemoryItem]:
    """在候选集上算 BM25，按分数取 Top-k（分≤0 的丢掉）。"""
    if not items or limit <= 0:
        return []
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    docs = [tokenize(item.searchable_text()) for item in items]
    scores = bm25(query_tokens, docs)
    ranked = sorted(
        ((item, float(score)) for item, score in zip(items, scores) if score > 0),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [item for item, _ in ranked[:limit]]


def recall_ranked_lanes(
    user_id: str,
    query: str,
    *,
    limit: int,
    config: MemoryConfig,
    query_embedding: Optional[Sequence[float]] = None,
    now: Optional[datetime] = None,
) -> tuple[list[MemoryItem], list[MemoryItem]]:
    """双路有序召回：关键词 BM25 Top-k、向量 Top-k（均已做有效性过滤）。"""
    k = max(1, int(limit))
    # FTS 先拉一池再 BM25 精排，避免只用 ts_rank 冒充 BM25。
    fts_pool = max(k * 10, 50)
    keyword_pool = _rows_to_valid_items(
        _keyword_lane(user_id, query, fts_pool),
        now,
    )
    keyword_lane = _bm25_topk(query, keyword_pool, k)

    vector_lane: list[MemoryItem] = []
    if query_embedding:
        # 多取一些再滤 TTL，尽量凑满 k 条有效结果。
        vector_pool = _rows_to_valid_items(
            _vector_lane(
                user_id,
                query_embedding,
                max(k * 3, k),
                config.min_cosine,
            ),
            now,
        )
        vector_lane = vector_pool[:k]

    return keyword_lane, vector_lane


def recall_candidates(
    user_id: str,
    query: str,
    *,
    limit: int,
    config: MemoryConfig,
    query_embedding: Optional[Sequence[float]] = None,
    now: Optional[datetime] = None,
) -> list[MemoryItem]:
    """兼容旧调用：返回两路并集（无序）；正式检索请用 ``recall_ranked_lanes``。"""
    keyword_lane, vector_lane = recall_ranked_lanes(
        user_id,
        query,
        limit=limit,
        config=config,
        query_embedding=query_embedding,
        now=now,
    )
    merged: dict[str, MemoryItem] = {}
    for item in keyword_lane + vector_lane:
        merged.setdefault(item.id, item)
    return list(merged.values())
