"""评测结果 JSON API，展示层由外部前端负责。"""

from __future__ import annotations

from fastapi import APIRouter

from ..evaluation_metrics import load_latest

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/metrics")
async def get_metrics():
    return load_latest()
