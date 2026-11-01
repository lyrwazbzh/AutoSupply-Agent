"""PostgreSQL COLD 混合检索：关键词 + pgvector + RRF。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from ...database import get_pg_pool
from ..knowledge.embeddings import encode_text
from . import namespaces as ns
from . import scoring
from .config import MemoryConfig
from .types import MemoryItem, now_iso

_RRF_K = 60


def _prefixes(user_id: str) -> tuple[str, str, str]:
    return tuple(".".join(parts) for parts in ns.user_namespaces(user_id))


def _keyword_text(item: MemoryItem) -> str:
    tool_text = json.dumps(item.tool_results, ensure_ascii=False, default=str)
    return " ".join(part for part in (item.searchable_text(), tool_text) if part)


def _semantic_text(item: MemoryItem) -> str:
    return " ".join(
        part for part in (item.summary, item.goal, item.outcome, item.content) if part
    )


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10g}" for value in vector) + "]"


def _http_embedding(text: str) -> list[float]:
    vector, backend = encode_text(text)
    return vector if backend == "http" else []


def index_item(user_id: str, item: MemoryItem) -> None:
    """更新现有 Store 行的检索文本；内容未变化时不重复生成向量。"""
    prefix = ".".join(ns.type_ns(user_id, item.type))
    keyword_text = _keyword_text(item)
    semantic_text = _semantic_text(item)
    semantic_hash = hashlib.sha256(semantic_text.encode("utf-8")).hexdigest()

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

    vector = _http_embedding(semantic_text)
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
            SELECT store.prefix, store.key, store.value,
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
    user_id: str, query: str, limit: int, min_score: float
) -> list[dict[str, Any]]:
    vector = _http_embedding(query)
    if not vector:
        return []
    literal = _vector_literal(vector)
    prefixes = _prefixes(user_id)
    with get_pg_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT prefix, key, value,
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
                len(vector),
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


def hybrid_search(
    user_id: str,
    query: str,
    *,
    k: int,
    config: MemoryConfig,
    touch: bool = True,
) -> list[tuple[MemoryItem, float]]:
    recall_k = max(20, k * 4)
    lanes = [
        _keyword_lane(user_id, query, recall_k),
        _vector_lane(
            user_id,
            query,
            recall_k,
            config.min_retrieval_score,
        ),
    ]
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for lane in lanes:
        for rank, row in enumerate(lane, 1):
            key = (str(row["prefix"]), str(row["key"]))
            entry = merged.setdefault(key, {"row": row, "rrf": 0.0})
            entry["rrf"] += 1.0 / (_RRF_K + rank)

    now = datetime.now()
    ranked: list[tuple[MemoryItem, float, tuple[str, str]]] = []
    for key, entry in merged.items():
        item = MemoryItem.from_dict(entry["row"].get("value"))
        if item is None:
            continue
        boost = (
            1.0
            + config.weight_recency
            * scoring.recency_score(item.age_days(now), config.half_life_days)
            + config.weight_access * scoring.access_score(item.access_count)
            + config.weight_confidence * max(0.0, min(1.0, item.confidence))
        )
        ranked.append((item, float(entry["rrf"]) * boost, key))

    ranked.sort(key=lambda value: value[1], reverse=True)
    selected = ranked[:k]
    if touch and selected:
        _touch_rows([key for _, _, key in selected])
    return [(item, score) for item, score, _ in selected]
