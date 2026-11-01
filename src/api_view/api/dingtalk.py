"""钉钉 webhook / 审批回调 HTTP 入口。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..dingtalk_channel import (
    DingTalkStreamConsumer,
    parse_approval_callback,
    publish_shortage_approval,
    verify_dingtalk_sign,
)

router = APIRouter(prefix="/api/dingtalk", tags=["dingtalk"])
_stream = DingTalkStreamConsumer()


class FreezePushBody(BaseModel):
    thread_id: str
    frozen_suggestion: dict[str, Any]
    dingtalk_userid: Optional[str] = None
    exposure_level: str = "medium"


@router.get("/health")
async def dingtalk_health():
    return {"ok": True, "service": "dingtalk-hitl"}


@router.post("/approvals/push")
async def push_approval(body: FreezePushBody):
    """渲染并推送缺料审批卡（webhook/robot/dry_run）。"""
    return publish_shortage_approval(
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
    """钉钉审批/互动卡片回调 → HITL resume 载荷。"""
    if timestamp and sign and not verify_dingtalk_sign(timestamp, sign):
        raise HTTPException(status_code=403, detail="invalid dingtalk signature")
    # 开放平台 URL 校验挑战
    if body.get("encrypt") and not body.get("decision") and not body.get("value"):
        return {"msg_signature": body.get("msg_signature"), "echo": True}
    result = parse_approval_callback(body)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "callback failed")
    return result


@router.post("/stream/event")
async def stream_event(event: dict[str, Any]):
    """外部 Stream 长连接进程把事件推入；本服务做幂等分发。"""
    return _stream.handle_event(event)
