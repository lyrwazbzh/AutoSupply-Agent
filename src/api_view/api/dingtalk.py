"""钉钉 webhook / 审批回调 HTTP 入口。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ..agent_loader import agent_loader
from ..auth import AuthenticatedPrincipal, require_permission
from ..dingtalk_channel import (
    DingTalkStreamConsumer,
    parse_approval_callback,
    publish_approval,
    verify_dingtalk_sign,
)

router = APIRouter(prefix="/api/dingtalk", tags=["dingtalk"])
_stream = DingTalkStreamConsumer()


async def _persist_approval(result: dict[str, Any]) -> dict[str, Any]:
    identity = result["identity"]
    decision = result["approval_decision"]
    await agent_loader.initialize()
    try:
        approval = await asyncio.to_thread(
            agent_loader.write_audit_repository.decide_approval,
            decision["operation_id"],
            decision=decision["decision"],
            actor_id=identity["agent_user_id"],
            note=decision.get("note", ""),
            expected_payload_hash=decision.get("payload_hash", ""),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="审批任务不存在") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"ok": True, "approval": approval, "card_id": result.get("card_id")}


class FreezePushBody(BaseModel):
    thread_id: str
    frozen_suggestion: dict[str, Any]
    dingtalk_userid: Optional[str] = None
    exposure_level: str = "medium"


@router.get("/health")
async def dingtalk_health():
    return {"ok": True, "service": "dingtalk-hitl"}


@router.post("/approvals/push")
async def push_approval(
    body: FreezePushBody,
    _: AuthenticatedPrincipal = Depends(require_permission("erp:order:approve")),
):
    """渲染并推送采购审批卡（webhook/robot/dry_run）。"""
    return publish_approval(
        thread_id=body.thread_id,
        frozen_suggestion=body.frozen_suggestion,
        userid=body.dingtalk_userid,
        exposure_level=body.exposure_level,
    )


@router.post("/callback")
async def approval_callback(
    body: dict[str, Any],
    timestamp: Optional[str] = Header(default=None, alias="timestamp"),
    sign: Optional[str] = Header(default=None, alias="sign"),
):
    """钉钉审批/互动卡片回调 → 按 operation_id 持久化独立决定。"""
    if not verify_dingtalk_sign(timestamp or "", sign or ""):
        raise HTTPException(status_code=403, detail="invalid dingtalk signature")
    # 开放平台 URL 校验挑战
    if body.get("encrypt") and not body.get("decision") and not body.get("value"):
        return {"msg_signature": body.get("msg_signature"), "echo": True}
    result = parse_approval_callback(body)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "callback failed")
    return await _persist_approval(result)


@router.post("/stream/event")
async def stream_event(
    event: dict[str, Any],
    _: AuthenticatedPrincipal = Depends(require_permission("erp:order:approve")),
):
    """外部 Stream 长连接进程把事件推入；本服务做幂等分发。"""
    result = _stream.handle_event(event)
    if not result.get("ok") or result.get("dedup") or result.get("type") == "chat":
        return result
    return await _persist_approval(result)
