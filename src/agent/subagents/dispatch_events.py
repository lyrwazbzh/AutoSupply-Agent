"""请求级委派事件缓冲：供 TaskDispatch 发布、SSE 流 drain。"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any


_dispatch_events: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "erp_agent_dispatch_events", default=None
)


def bind_dispatch_events() -> Token:
    """为本请求绑定空事件列表。"""
    return _dispatch_events.set([])


def reset_dispatch_events(token: Token) -> None:
    _dispatch_events.reset(token)


def publish_dispatch_event(event: dict[str, Any]) -> None:
    """写入当前请求缓冲；未绑定时丢弃（非流式/单测可仍靠 logger）。"""
    buf = _dispatch_events.get()
    if buf is not None:
        buf.append(dict(event))


def drain_dispatch_events() -> list[dict[str, Any]]:
    """取出并清空当前缓冲中的事件。"""
    buf = _dispatch_events.get()
    if not buf:
        return []
    items = list(buf)
    buf.clear()
    return items


def overlapping_dispatch_pairs(events: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """根据 started_at/finished_at 找出时间重叠的派发对（用于验真并行）。"""
    from datetime import datetime

    spans: list[tuple[str, datetime, datetime]] = []
    for ev in events:
        if ev.get("type") != "agent_dispatch" or ev.get("phase") != "end":
            continue
        call_id = str(ev.get("call_id") or "")
        started = ev.get("started_at")
        finished = ev.get("finished_at")
        if not call_id or not started or not finished:
            continue
        try:
            t0 = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
        except ValueError:
            continue
        spans.append((call_id, t0, t1))

    pairs: list[tuple[str, str]] = []
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            a_id, a0, a1 = spans[i]
            b_id, b0, b1 = spans[j]
            if a0 < b1 and b0 < a1:
                pairs.append((a_id, b_id))
    return pairs
