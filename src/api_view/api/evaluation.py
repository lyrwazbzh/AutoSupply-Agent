"""评测结果 JSON API，展示层由外部前端负责。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...evaluation.report_store import load_report
from .. import auth
from ..agent_loader import agent_loader

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/metrics")
async def get_metrics(
    _: str | None = Depends(auth.current_user_id),
):
    permission_check = getattr(auth, "assert_permission", None)
    if permission_check is not None:
        permission_check("audit:read:all")
    try:
        return load_report()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/traces/{thread_id}")
async def get_evaluation_trace(
    thread_id: str,
    authenticated: str | None = Depends(auth.current_user_id),
):
    permission_check = getattr(auth, "assert_permission", None)
    if permission_check is not None:
        permission_check("assistant:use")
    owner = await agent_loader.get_conversation_user_id(thread_id)
    auth.assert_thread_owner(thread_id, owner, authenticated)
    return {
        "thread_id": thread_id,
        "trace": await agent_loader.get_harness_trace(thread_id),
    }
