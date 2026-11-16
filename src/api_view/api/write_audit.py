"""写审计 API：用户轨迹查询 + 运维人工结案。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..agent_loader import agent_loader
from ..auth import assert_permission, current_user_id, resolve_user_id

router = APIRouter(prefix="/api/write-audit", tags=["write-audit"])


class ResolveManualBody(BaseModel):
    resolution: str = Field(
        description="succeeded | not_applied | abandoned",
    )
    note: str = ""
    actor_id: str | None = None


class ApprovalDecisionBody(BaseModel):
    decision: str = Field(description="approve | reject")
    note: str = ""
    payload_hash: str = ""


@router.get("")
async def list_write_operations(
    user_id: str = Query(default="default_user"),
    thread_id: str | None = None,
    status: str | None = None,
    tool_name: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    authenticated: str | None = Depends(current_user_id),
):
    assert_permission("audit:read:self", "audit:read:all")
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
    assert_permission("audit:read:all")
    if not authenticated:
        raise HTTPException(status_code=401, detail="需要登录后查看人工队列")
    await agent_loader.initialize()
    rows = await asyncio.to_thread(
        agent_loader.write_audit_repository.list_manual_required,
        limit=limit,
    )
    return {"operations": rows}


@router.get("/approval-queue")
async def list_approval_queue(
    limit: int = Query(default=100, ge=1, le=500),
    authenticated: str | None = Depends(current_user_id),
):
    """管理员审批台：只返回独立任务及脱敏业务载荷，不读取申请人会话。"""
    assert_permission("erp:order:approve")
    if not authenticated:
        raise HTTPException(status_code=401, detail="需要登录后查看审批队列")
    await agent_loader.initialize()
    rows = await asyncio.to_thread(
        agent_loader.write_audit_repository.list_pending_approvals,
        limit=limit,
    )
    return {"approvals": rows}


@router.post("/approvals/{operation_id}/decision")
async def decide_approval(
    operation_id: str,
    body: ApprovalDecisionBody,
    authenticated: str | None = Depends(current_user_id),
):
    """按 operation_id 决策；管理员既不需要也不能借此访问申请人会话。"""
    assert_permission("erp:order:approve")
    actor = (authenticated or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="需要登录后审批")
    await agent_loader.initialize()
    try:
        approval = await asyncio.to_thread(
            agent_loader.write_audit_repository.decide_approval,
            operation_id,
            decision=body.decision,
            actor_id=actor,
            note=body.note,
            expected_payload_hash=body.payload_hash,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="审批任务不存在") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"approval": approval}


@router.get("/{operation_id}")
async def get_write_operation(
    operation_id: str,
    user_id: str = Query(default="default_user"),
    authenticated: str | None = Depends(current_user_id),
):
    assert_permission("audit:read:self", "audit:read:all")
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
    assert_permission("audit:resolve")
    actor = (authenticated or body.actor_id or "").strip()
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
