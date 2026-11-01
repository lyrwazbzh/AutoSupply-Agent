"""Embedding 客户端：优先 HTTP 推理服务，失败降级本地词袋向量。"""

from __future__ import annotations

import hashlib
import logging
import math

import httpx

from . import settings
from .store import tokenize

logger = logging.getLogger(__name__)


def is_embedding_available() -> bool:
    url = settings.EMBEDDING_SERVER_URL
    if not url:
        return False
    try:
        r = httpx.get(f"{url}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _http_embed(texts: list[str]) -> list[list[float]]:
    url = settings.EMBEDDING_SERVER_URL
    if not url:
        raise RuntimeError("未配置 KNOWLEDGE_EMBEDDING_URL")
    r = httpx.post(
        f"{url}/v1/embeddings",
        json={"model": settings.EMBEDDING_MODEL, "input": texts},
        timeout=settings.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()["data"]
    data.sort(key=lambda x: x["index"])
    return [d["embedding"] for d in data]


def _bow_embed(text: str, dim_hint: int = 256) -> list[float]:
    """确定性本地降级向量（hash 桶），无外部服务时保证链路可跑。"""
    vec = [0.0] * dim_hint
    for tok in tokenize(text):
        # Python's built-in hash is randomized per process and would make
        # persisted pgvector embeddings invalid after a restart.
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        h = int.from_bytes(digest[:8], "big") % dim_hint
        vec[h] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def encode_texts(texts: list[str]) -> tuple[list[list[float]], str]:
    """返回 (向量列表, backend=http|bow)。"""
    if not texts:
        return [], "empty"
    try:
        if settings.EMBEDDING_SERVER_URL and is_embedding_available():
            return _http_embed(texts), "http"
    except Exception as e:
        logger.warning("Embedding HTTP 不可用，降级 bow: %s", e)
    return [_bow_embed(t) for t in texts], "bow"


def encode_text(text: str) -> tuple[list[float], str]:
    vecs, backend = encode_texts([text])
    return (vecs[0] if vecs else []), backend


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
