"""知识检索配置（环境变量可覆盖；对齐 Smart-Repair 能力开关）。"""

from __future__ import annotations

import os


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# Embedding / Reranker 独立推理服务（OpenAI 兼容）；不可用时自动降级
EMBEDDING_SERVER_URL = os.getenv("KNOWLEDGE_EMBEDDING_URL", "").rstrip("/")
RERANKER_SERVER_URL = os.getenv("KNOWLEDGE_RERANKER_URL", "").rstrip("/")
EMBEDDING_MODEL = os.getenv("KNOWLEDGE_EMBEDDING_MODEL", "text-embedding-3-small")
RERANKER_MODEL = os.getenv("KNOWLEDGE_RERANKER_MODEL", "reranker")

RERANKER_ENABLED = _bool("KNOWLEDGE_RERANKER_ENABLED", True)
RERANKER_CANDIDATES = _int("KNOWLEDGE_RERANKER_CANDIDATES", 12)
RECALL_TOP_K = _int("KNOWLEDGE_RECALL_TOP_K", 12)
FINAL_TOP_N = _int("KNOWLEDGE_FINAL_TOP_N", 5)
COARSE_THRESHOLD = _float("KNOWLEDGE_COARSE_THRESHOLD", 0.08)
RRF_K = _int("KNOWLEDGE_RRF_K", 60)
HTTP_TIMEOUT = _float("KNOWLEDGE_HTTP_TIMEOUT", 8.0)
