"""记忆向量：OpenAI 兼容 Embeddings HTTP API + 余弦。

Keeper 在写入时把向量存进 MemoryItem；检索时对改写后的问句编码，
与候选向量比余弦。无 API 配置时 embedder 为 None，检索只走 BM25。
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Protocol, Sequence


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


class HttpEmbedder:
    """OpenAI 兼容 ``POST {base}/embeddings``。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 15.0,
    ):
        self._url = base_url.rstrip("/") + "/embeddings"
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        payload = json.dumps(
            {"model": self._model, "input": list(texts)},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=self._timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        data = body.get("data") or []
        ordered = sorted(data, key=lambda row: int(row.get("index", 0)))
        return [list(row.get("embedding") or []) for row in ordered]


def build_http_embedder(
    base_url: str,
    api_key: str,
    model: str,
) -> HttpEmbedder | None:
    if not (base_url or "").strip() or not (api_key or "").strip():
        return None
    return HttpEmbedder(base_url.strip(), api_key.strip(), model.strip() or "text-embedding-3-small")
