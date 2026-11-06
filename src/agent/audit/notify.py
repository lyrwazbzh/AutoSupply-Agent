"""写审计值班通知：MANUAL_REQUIRED 时发钉钉 / 邮件。

未配置渠道时干跑打日志，不阻断对账主流程。
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _dingtalk_targets() -> tuple[str, str]:
    webhook = (
        os.getenv("WRITE_AUDIT_DINGTALK_WEBHOOK", "").strip()
        or os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
    )
    token = (
        os.getenv("WRITE_AUDIT_DINGTALK_TOKEN", "").strip()
        or os.getenv("DINGTALK_ACCESS_TOKEN", "").strip()
    )
    return webhook.rstrip("/"), token


def _email_config() -> dict[str, str]:
    return {
        "host": os.getenv("WRITE_AUDIT_SMTP_HOST", "").strip(),
        "port": os.getenv("WRITE_AUDIT_SMTP_PORT", "587").strip(),
        "user": os.getenv("WRITE_AUDIT_SMTP_USER", "").strip(),
        "password": os.getenv("WRITE_AUDIT_SMTP_PASSWORD", "").strip(),
        "from_addr": (
            os.getenv("WRITE_AUDIT_SMTP_FROM", "").strip()
            or os.getenv("WRITE_AUDIT_SMTP_USER", "").strip()
        ),
        "to_addrs": os.getenv("WRITE_AUDIT_ALERT_EMAIL", "").strip(),
    }


def _format_message(operation: dict[str, Any], error: str | None) -> tuple[str, str]:
    operation_id = str(operation.get("operation_id") or "")
    tool = str(operation.get("tool_name") or "")
    user_id = str(operation.get("user_id") or "")
    thread_id = str(operation.get("thread_id") or "")
    title = f"[写审计] MANUAL_REQUIRED operation={operation_id}"
    body = "\n".join(
        [
            "ERP 写操作对账需人工处理",
            f"operation_id: {operation_id}",
            f"tool: {tool}",
            f"user_id: {user_id}",
            f"thread_id: {thread_id}",
            f"error: {(error or '')[:1000]}",
            "结案: POST /api/write-audit/{operation_id}/resolve-manual",
        ]
    )
    return title, body


def notify_dingtalk(title: str, body: str) -> dict[str, Any]:
    webhook, token = _dingtalk_targets()
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": f"### {title}\n\n```\n{body}\n```"},
    }
    timeout = float(os.getenv("WRITE_AUDIT_NOTIFY_TIMEOUT", "8"))
    if webhook:
        try:
            response = httpx.post(webhook, json=payload, timeout=timeout)
            response.raise_for_status()
            return {"ok": True, "channel": "webhook"}
        except Exception as exc:
            logger.warning("写审计钉钉 webhook 失败: %s", exc)
            return {"ok": False, "channel": "webhook", "error": str(exc)}
    if token:
        url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
        try:
            response = httpx.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            return {"ok": True, "channel": "robot"}
        except Exception as exc:
            logger.warning("写审计钉钉 robot 失败: %s", exc)
            return {"ok": False, "channel": "robot", "error": str(exc)}
    logger.warning("%s\n%s", title, body)
    return {"ok": True, "channel": "dry_run"}


def notify_email(title: str, body: str) -> dict[str, Any]:
    cfg = _email_config()
    if not cfg["host"] or not cfg["to_addrs"]:
        return {"ok": True, "channel": "email_skipped"}
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = cfg["from_addr"] or "noreply@localhost"
    message["To"] = cfg["to_addrs"]
    message.set_content(body)
    try:
        port = int(cfg["port"] or "587")
        with smtplib.SMTP(cfg["host"], port, timeout=10) as smtp:
            smtp.ehlo()
            if port != 25:
                smtp.starttls()
                smtp.ehlo()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(message)
        return {"ok": True, "channel": "email"}
    except Exception as exc:
        logger.warning("写审计邮件通知失败: %s", exc)
        return {"ok": False, "channel": "email", "error": str(exc)}


def notify_manual_required(
    operation: dict[str, Any] | None,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    """对账升到 MANUAL_REQUIRED 后调用；渠道失败只记日志。"""
    op = dict(operation or {})
    title, body = _format_message(op, error)
    return {
        "dingtalk": notify_dingtalk(title, body),
        "email": notify_email(title, body),
    }
