"""Okapi BM25 关键词召回（相对 Smart-Repair 文档中 ILIKE 加权的标准实现）。"""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable

from .store import KnowledgeDoc, tokenize


class BM25Index:
    def __init__(self, docs: list[KnowledgeDoc], *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs = list(docs)
        self._doc_tokens: list[list[str]] = []
        self._doc_len: list[int] = []
        self._df: Counter = Counter()
        self._avgdl = 0.0
        self._rebuild()

    def _rebuild(self) -> None:
        self._doc_tokens = []
        self._doc_len = []
        self._df = Counter()
        for doc in self.docs:
            # 标题加权：标题 token 重复一次，提升标题命中
            toks = tokenize(doc.title) + tokenize(doc.title) + tokenize(doc.content)
            self._doc_tokens.append(toks)
            self._doc_len.append(len(toks))
            for t in set(toks):
                self._df[t] += 1
        n = len(self.docs) or 1
        self._avgdl = sum(self._doc_len) / n

    def search(self, query: str, top_k: int = 10) -> list[tuple[KnowledgeDoc, float]]:
        q_tokens = tokenize(query)
        if not q_tokens or not self.docs:
            return []
        n = len(self.docs)
        scores: list[tuple[int, float]] = []
        for i, toks in enumerate(self._doc_tokens):
            tf = Counter(toks)
            score = 0.0
            dl = self._doc_len[i] or 1
            for qt in q_tokens:
                if qt not in tf:
                    continue
                df = self._df.get(qt, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                freq = tf[qt]
                denom = freq + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1))
                score += idf * (freq * (self.k1 + 1)) / (denom or 1)
            if score > 0:
                scores.append((i, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [(self.docs[i], s) for i, s in scores[:top_k]]


_INDEX_CACHE: dict[int, BM25Index] = {}


def get_bm25_index(docs: Iterable[KnowledgeDoc]) -> BM25Index:
    docs_list = list(docs)
    # 简单缓存：文档集合变化时重建
    sig = hash(tuple((d.id, d.version, len(d.content)) for d in docs_list))
    cached = _INDEX_CACHE.get(sig)
    if cached is not None:
        return cached
    idx = BM25Index(docs_list)
    _INDEX_CACHE.clear()
    _INDEX_CACHE[sig] = idx
    return idx
