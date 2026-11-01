"""Read-only API for user-scoped ERP write audit trails."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from ..agent_loader import agent_loader
from ..auth import current_user_id, resolve_user_id

router = APIRouter(prefix="/api/write-audit", tags=["write-audit"])


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
