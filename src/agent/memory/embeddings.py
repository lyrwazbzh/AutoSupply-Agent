"""记忆向量：OpenAI 兼容 Embeddings HTTP API + 余弦；失败可降级本地词袋。

只读 MEMORY_EMBEDDING_*（及 OPENAI_API_KEY）；与知识侧 embeddings 互不依赖。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import urllib.error
import urllib.request
from typing import Protocol, Sequence

logger = logging.getLogger(__name__)

_BOW_DIM = 256


class Embedder(Protocol):
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...


def cosine(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for a, b in zip(left, right):
        dot += a * b
        na += a * a
        nb += b * b
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / math.sqrt(na * nb)))


def _embeddings_endpoint(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/embeddings"):
        return base
    if base.endswith("/v1"):
        return base + "/embeddings"
    return base + "/v1/embeddings"


def _resolve_embedding_config(
    base_url: str = "",
    api_key: str = "",
    model: str = "",
) -> tuple[str, str, str]:
    url = (
        (base_url or "").strip()
        or os.getenv("MEMORY_EMBEDDING_BASE_URL", "").strip()
    )
    key = (
        (api_key or "").strip()
        or os.getenv("MEMORY_EMBEDDING_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )
    name = (
        (model or "").strip()
        or os.getenv("MEMORY_EMBEDDING_MODEL", "").strip()
        or "text-embedding-3-small"
    )
    return url, key, name


class HttpEmbedder:
    """OpenAI 兼容 ``POST {base}/v1/embeddings``。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 15.0,
    ):
        self._url = _embeddings_endpoint(base_url)
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        payload = json.dumps(
            {"model": self._model, "input": list(texts)},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            self._url,
            data=payload,
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=self._timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        data = body.get("data") or []
        ordered = sorted(data, key=lambda row: int(row.get("index", 0)))
        return [list(row.get("embedding") or []) for row in ordered]


def build_http_embedder(
    base_url: str = "",
    api_key: str = "",
    model: str = "",
) -> HttpEmbedder | None:
    url, key, name = _resolve_embedding_config(base_url, api_key, model)
    if not url:
        return None
    return HttpEmbedder(url, key, name)


def is_embedding_available(
    base_url: str = "",
    api_key: str = "",
    model: str = "",
) -> bool:
    embedder = build_http_embedder(base_url, api_key, model)
    if embedder is None:
        return False
    try:
        vectors = embedder.embed_texts(["ping"])
        return bool(vectors and vectors[0])
    except Exception:
        return False


def _bow_tokens(text: str) -> list[str]:
    from .scoring import tokenize

    return tokenize(text)


def _bow_embed(text: str, dim_hint: int = _BOW_DIM) -> list[float]:
    """确定性本地降级向量（hash 桶），无外部服务时保证链路可跑。"""
    vec = [0.0] * dim_hint
    for tok in _bow_tokens(text):
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        h = int.from_bytes(digest[:8], "big") % dim_hint
        vec[h] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def encode_texts(
    texts: list[str],
    *,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
) -> tuple[list[list[float]], str]:
    """返回 (向量列表, backend=http|bow|empty)。"""
    if not texts:
        return [], "empty"
    embedder = build_http_embedder(base_url, api_key, model)
    if embedder is not None:
        try:
            return embedder.embed_texts(texts), "http"
        except Exception as exc:
            logger.warning("Embedding HTTP 不可用，降级 bow: %s", exc)
    return [_bow_embed(text) for text in texts], "bow"


def encode_text(
    text: str,
    *,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
) -> tuple[list[float], str]:
    vectors, backend = encode_texts(
        [text],
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
    return (vectors[0] if vectors else []), backend
