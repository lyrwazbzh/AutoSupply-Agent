"""写审计 API：用户轨迹查询 + 运维人工结案。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..agent_loader import agent_loader
from ..auth import current_user_id, resolve_user_id

router = APIRouter(prefix="/api/write-audit", tags=["write-audit"])


class ResolveManualBody(BaseModel):
    resolution: str = Field(
        description="succeeded | not_applied | abandoned",
    )
    note: str = ""
    actor_id: str | None = None


@router.get("")
async def list_write_operations(
    user_id: str = Query(default="default_user"),
    thread_id: str | None = None,
    status: str | None = None,
    tool_name: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    authenticated: str | None = Depends(current_user_id),
):
    await agent_loader.initialize()
    effective_user = resolve_user_id(authenticated, user_id)
    rows = await asyncio.to_thread(
        agent_loader.write_audit_repository.list_operations,
        user_id=effective_user,
        thread_id=thread_id,
        status=status,
        tool_name=tool_name,
        limit=limit,
    )
    return {"operations": rows}


@router.get("/manual-queue")
async def list_manual_queue(
    limit: int = Query(default=100, ge=1, le=500),
    authenticated: str | None = Depends(current_user_id),
):
    """运维台：全部 MANUAL_REQUIRED 待结案队列。"""
    if not authenticated:
        raise HTTPException(status_code=401, detail="需要登录后查看人工队列")
    await agent_loader.initialize()
    rows = await asyncio.to_thread(
        agent_loader.write_audit_repository.list_manual_required,
        limit=limit,
    )
    return {"operations": rows}


@router.get("/{operation_id}")
async def get_write_operation(
    operation_id: str,
    user_id: str = Query(default="default_user"),
    authenticated: str | None = Depends(current_user_id),
):
    await agent_loader.initialize()
    effective_user = resolve_user_id(authenticated, user_id)
    item = await asyncio.to_thread(
        agent_loader.write_audit_repository.get_operation_with_events,
        operation_id,
        user_id=effective_user,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="写操作审计记录不存在")
    return item


@router.post("/{operation_id}/resolve-manual")
async def resolve_manual(
    operation_id: str,
    body: ResolveManualBody,
    authenticated: str | None = Depends(current_user_id),
):
    """运维确认已人工处理并结案（仅 MANUAL_REQUIRED）。"""
    actor = (body.actor_id or authenticated or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="需要登录或提供 actor_id")
    await agent_loader.initialize()
    try:
        operation = await asyncio.to_thread(
            agent_loader.write_audit_repository.resolve_manual,
            operation_id,
            resolution=body.resolution,
            actor_id=actor,
            note=body.note,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="写操作审计记录不存在") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"operation": operation}
