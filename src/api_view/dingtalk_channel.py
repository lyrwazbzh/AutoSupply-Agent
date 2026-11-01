"""
钉钉 HITL 通道适配层

钉钉仅做身份映射与审批卡片通道；写单仍走现有 HumanInTheLoop / order_create。
支持：
- 身份映射
- 审批卡渲染（Interactive Card 协议字段）
- 出站推送（HTTP webhook / 开放平台机器人，可配置）
- 入站回调 → HITL resume
- Stream 事件消费骨架（长连接由外部进程喂入事件）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal, Optional

import httpx

logger = logging.getLogger(__name__)

Decision = Literal["approve", "reject"]


@dataclass
class DingTalkIdentity:
    """钉钉用户 → 采购 Agent 用户。"""

    dingtalk_userid: str
    agent_user_id: str
    display_name: str = ""
    roles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFAULT_IDENTITY_MAP: dict[str, DingTalkIdentity] = {
    "ding-buyer-001": DingTalkIdentity(
        dingtalk_userid="ding-buyer-001",
        agent_user_id="buyer",
        display_name="采购员演示账号",
        roles=["purchaser"],
    ),
}


def load_identity_map_from_env() -> dict[str, DingTalkIdentity]:
    """DINGTALK_IDENTITY_JSON='{"uid":{"agent_user_id":"buyer","roles":["purchaser"]}}'"""
    raw = os.getenv("DINGTALK_IDENTITY_JSON", "").strip()
    if not raw:
        return dict(_DEFAULT_IDENTITY_MAP)
    try:
        data = json.loads(raw)
        out: dict[str, DingTalkIdentity] = {}
        for uid, row in data.items():
            out[uid] = DingTalkIdentity(
                dingtalk_userid=uid,
                agent_user_id=str(row.get("agent_user_id") or uid),
                display_name=str(row.get("display_name") or ""),
                roles=list(row.get("roles") or ["purchaser"]),
            )
        return out or dict(_DEFAULT_IDENTITY_MAP)
    except Exception:
        logger.warning("DINGTALK_IDENTITY_JSON 解析失败，使用默认映射")
        return dict(_DEFAULT_IDENTITY_MAP)


def map_dingtalk_user(
    dingtalk_userid: str,
    mapping: Optional[dict[str, DingTalkIdentity]] = None,
) -> Optional[DingTalkIdentity]:
    table = mapping if mapping is not None else load_identity_map_from_env()
    return table.get(dingtalk_userid)


@dataclass
class DingTalkApprovalCard:
    """审批卡片：展示固化建议，回调后转为 HITL decisions。"""

    card_id: str
    thread_id: str
    suggestion_id: str
    calc_run_id: str
    title: str
    summary_lines: list[str]
    total_amount: float
    idempotency_key: str
    order_payload: dict[str, Any]
    exposure_level: str = "medium"
    interactive_card: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def render_approval_card(
    *,
    thread_id: str,
    frozen_suggestion: dict[str, Any],
    title: str = "缺料补货采购审批",
    exposure_level: str = "medium",
) -> DingTalkApprovalCard:
    """从 freeze_shortage_suggestion 结果生成钉钉可渲染的审批卡数据。"""
    payload = frozen_suggestion.get("order_payload") or {}
    details = payload.get("orderDetail") or []
    amount = float(frozen_suggestion.get("total_amount") or 0)
    lines = [
        f"suggestion={frozen_suggestion.get('suggestion_id')}",
        f"calc_run_id={frozen_suggestion.get('calc_run_id')}",
        f"明细 {len(details)} 行 / 金额 {amount}",
        f"暴露风险={exposure_level}",
    ]
    for row in details[:5]:
        lines.append(
            f"- partId={row.get('partId')} qty={row.get('quantity')} price={row.get('unitPrice')}"
        )
    if len(details) > 5:
        lines.append(f"… 另有 {len(details) - 5} 行")

    card_id = f"card-{frozen_suggestion.get('suggestion_id')}"
    interactive = {
        "config": {"autoLayout": True, "enableForward": False},
        "header": {"title": {"type": "text", "text": title}, "logo": "@lALPDfJ6V_FPDmvNAfTNAfQ"},
        "contents": [
            {"type": "markdown", "text": "\n".join(lines)},
            {
                "type": "action",
                "actions": [
                    {
                        "type": "button",
                        "label": {"type": "text", "text": "批准"},
                        "action_id": "approve",
                        "status": "primary",
                        "value": {"decision": "approve", "card_id": card_id, "thread_id": thread_id},
                    },
                    {
                        "type": "button",
                        "label": {"type": "text", "text": "拒绝"},
                        "action_id": "reject",
                        "status": "warning",
                        "value": {"decision": "reject", "card_id": card_id, "thread_id": thread_id},
                    },
                ],
            },
        ],
    }

    return DingTalkApprovalCard(
        card_id=card_id,
        thread_id=thread_id,
        suggestion_id=str(frozen_suggestion.get("suggestion_id") or ""),
        calc_run_id=str(frozen_suggestion.get("calc_run_id") or ""),
        title=title,
        summary_lines=lines,
        total_amount=amount,
        idempotency_key=str(frozen_suggestion.get("idempotency_key") or ""),
        order_payload=payload,
        exposure_level=exposure_level,
        interactive_card=interactive,
    )


def verify_dingtalk_sign(
    timestamp: str,
    sign: str,
    *,
    secret: Optional[str] = None,
) -> bool:
    """开放平台回调签名校验（timestamp+\\n+secret → HmacSHA256 → Base64）。"""
    import base64

    secret = secret or os.getenv("DINGTALK_CALLBACK_SECRET", "")
    if not secret:
        # 未配置密钥时开发模式放行，生产应配置
        return os.getenv("DINGTALK_SKIP_SIGN", "1") == "1"
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, sign or "")


def parse_approval_callback(
    body: dict[str, Any],
) -> dict[str, Any]:
    """
    将钉钉审批回调转为 LangGraph HITL resume 载荷。

    期望 body：
      { "card_id", "operation_id", "dingtalk_userid", "decision": "approve"|"reject", "thread_id" }
    或钉钉互动卡片回调嵌套 value 字段。
    """
    # 兼容互动卡片 actionCallback
    if "value" in body and isinstance(body["value"], dict):
        nested = body["value"]
        body = {
            **body,
            "decision": nested.get("decision") or body.get("decision"),
            "card_id": nested.get("card_id") or body.get("card_id"),
            "thread_id": nested.get("thread_id") or body.get("thread_id"),
            "operation_id": nested.get("operation_id") or body.get("operation_id"),
        }
        if not body.get("dingtalk_userid"):
            body["dingtalk_userid"] = (
                body.get("userId") or body.get("senderStaffId") or ""
            )

    userid = str(body.get("dingtalk_userid") or body.get("userId") or "")
    decision = str(body.get("decision") or "").lower()
    thread_id = str(body.get("thread_id") or "")
    identity = map_dingtalk_user(userid)

    if identity is None:
        return {
            "ok": False,
            "error": f"未映射的钉钉用户: {userid}",
            "identity": None,
            "hitl_resume": None,
            "thread_id": thread_id,
        }
    if decision not in ("approve", "reject"):
        return {
            "ok": False,
            "error": "decision 须为 approve|reject",
            "identity": identity.to_dict(),
            "hitl_resume": None,
            "thread_id": thread_id,
        }
    if "purchaser" not in identity.roles and "admin" not in identity.roles:
        return {
            "ok": False,
            "error": "无采购审批角色",
            "identity": identity.to_dict(),
            "hitl_resume": None,
            "thread_id": thread_id,
        }

    decision_payload: dict[str, Any] = {"type": decision}
    if body.get("operation_id"):
        decision_payload["operation_id"] = str(body["operation_id"])

    return {
        "ok": True,
        "error": None,
        "identity": identity.to_dict(),
        "thread_id": thread_id,
        "hitl_resume": {"decisions": [decision_payload]},
        "card_id": body.get("card_id"),
    }


class DingTalkCardPublisher:
    """出站推送审批卡：优先自定义 webhook，其次开放平台机器人。"""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        self.webhook_url = (webhook_url or os.getenv("DINGTALK_WEBHOOK_URL", "")).rstrip("/")
        self.access_token = access_token or os.getenv("DINGTALK_ACCESS_TOKEN", "")
        self.timeout = float(os.getenv("DINGTALK_HTTP_TIMEOUT", "8"))

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url or self.access_token)

    def push_approval_card(
        self,
        card: DingTalkApprovalCard,
        *,
        userid: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": card.title,
                "text": "\n\n".join(card.summary_lines),
                "btnOrientation": "0",
                "btns": [
                    {
                        "title": "批准",
                        "actionURL": f"https://hitl.local/approve?card_id={card.card_id}&thread_id={card.thread_id}",
                    },
                    {
                        "title": "拒绝",
                        "actionURL": f"https://hitl.local/reject?card_id={card.card_id}&thread_id={card.thread_id}",
                    },
                ],
            },
            "card": card.to_dict(),
            "interactive_card": card.interactive_card,
            "userid": userid,
        }
        if self.webhook_url:
            try:
                r = httpx.post(self.webhook_url, json=payload, timeout=self.timeout)
                r.raise_for_status()
                return {"ok": True, "channel": "webhook", "status_code": r.status_code, "body": _safe_json(r)}
            except Exception as e:
                logger.warning("钉钉 webhook 推送失败: %s", e)
                return {"ok": False, "channel": "webhook", "error": str(e), "payload": payload}

        if self.access_token:
            url = f"https://oapi.dingtalk.com/robot/send?access_token={self.access_token}"
            try:
                r = httpx.post(url, json=payload, timeout=self.timeout)
                r.raise_for_status()
                return {"ok": True, "channel": "robot", "status_code": r.status_code, "body": _safe_json(r)}
            except Exception as e:
                return {"ok": False, "channel": "robot", "error": str(e), "payload": payload}

        # 未配置外发：干跑，便于本地/E2E
        return {
            "ok": True,
            "channel": "dry_run",
            "message": "未配置 DINGTALK_WEBHOOK_URL / DINGTALK_ACCESS_TOKEN，已干跑",
            "payload": payload,
        }


def _safe_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return r.text[:500]


# Stream 事件消费：外部长连接进程把事件 dict 喂入
_StreamHandler = Callable[[dict[str, Any]], dict[str, Any]]


class DingTalkStreamConsumer:
    """Stream 事件分发骨架：chat / card_callback → 统一解析。"""

    def __init__(self, on_hitl: Optional[_StreamHandler] = None):
        self.on_hitl = on_hitl or parse_approval_callback
        self._seen: set[str] = set()

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("eventId") or event.get("msgid") or "")
        if event_id and event_id in self._seen:
            return {"ok": True, "dedup": True, "event_id": event_id}
        if event_id:
            self._seen.add(event_id)
            if len(self._seen) > 5000:
                self._seen = set(list(self._seen)[-2000:])

        etype = str(event.get("type") or event.get("EventType") or "card_callback")
        if etype in ("card_callback", "interactive_card", "actionCallback"):
            body = event.get("data") or event
            return self.on_hitl(body if isinstance(body, dict) else {})
        if etype in ("chat", "message"):
            return {
                "ok": True,
                "type": "chat",
                "text": (event.get("text") or event.get("content") or ""),
                "dingtalk_userid": event.get("senderStaffId") or event.get("userid"),
            }
        return {"ok": False, "error": f"未知事件类型: {etype}"}


def publish_shortage_approval(
    *,
    thread_id: str,
    frozen_suggestion: dict[str, Any],
    userid: Optional[str] = None,
    exposure_level: str = "medium",
) -> dict[str, Any]:
    """一站式：渲染 + 推送。"""
    card = render_approval_card(
        thread_id=thread_id,
        frozen_suggestion=frozen_suggestion,
        exposure_level=exposure_level,
    )
    push = DingTalkCardPublisher().push_approval_card(card, userid=userid)
    return {"card": card.to_dict(), "push": push}
