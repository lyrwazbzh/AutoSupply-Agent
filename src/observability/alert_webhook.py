"""Alertmanager 分级通知入口。"""

from __future__ import annotations

from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException

from ..agent.audit.notify import notify_dingtalk, notify_email
from ..agent.log_utils import get_logger

logger = get_logger("alert-webhook")
app = FastAPI(title="ERP Agent Alert Webhook")


def _message(payload: dict[str, Any], severity: str) -> tuple[str, str]:
    alerts = list(payload.get("alerts") or [])
    status = str(payload.get("status") or "firing").upper()
    title = f"[{severity.upper()}][{status}] ERP Agent 告警"
    lines = [f"group: {payload.get('groupKey') or ''}"]
    for alert in alerts:
        labels = dict(alert.get("labels") or {})
        annotations = dict(alert.get("annotations") or {})
        lines.extend(
            [
                "",
                f"alert: {labels.get('alertname') or ''}",
                f"service: {labels.get('service') or ''}",
                f"summary: {annotations.get('summary') or ''}",
                f"description: {annotations.get('description') or ''}",
                f"runbook: {annotations.get('runbook') or ''}",
                f"starts_at: {alert.get('startsAt') or ''}",
            ]
        )
    return title, "\n".join(lines)


@app.post("/alerts/{severity}")
async def receive_alerts(
    severity: Literal["critical", "warning"], payload: dict[str, Any]
) -> dict[str, Any]:
    title, body = _message(payload, severity)
    logger.warning("Alertmanager notification severity=%s body=%s", severity, body)
    result = {"dingtalk": notify_dingtalk(title, body)}
    if severity == "critical":
        result["email"] = notify_email(title, body)
    if any(not channel.get("ok", False) for channel in result.values()):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010, log_config=None)
