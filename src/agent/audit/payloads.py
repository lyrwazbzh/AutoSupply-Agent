"""Canonical hashing, redaction, and ERP result classification."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import ToolMessage

_SECRET_PARTS = (
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "api_key",
    "apikey",
    "access_key",
    "phone",
    "email",
    "address",
    "contact_person",
    "contactperson",
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "***REDACTED***"
                if any(part in str(key).lower() for part in _SECRET_PARTS)
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_content(value: Any) -> Any:
    content = getattr(value, "content", value)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (TypeError, ValueError):
            return {"message": content[:2000]}
    return content


def classify_tool_result(result: Any) -> tuple[bool, Any, str | None, str | None]:
    """Return ``(success, parsed, error, erp_reference)``."""

    parsed = parse_content(result)
    if isinstance(result, ToolMessage) and getattr(result, "status", None) == "error":
        return False, parsed, _message(parsed), None
    if isinstance(parsed, dict):
        code = parsed.get("code")
        success = parsed.get("success")
        data = parsed.get("data")
        unknown = isinstance(data, dict) and data.get("operationStatus") == "UNKNOWN"
        if unknown or code in (202, "202"):
            return False, parsed, "ERP_RESULT_UNKNOWN", _reference(data)
        if success is False or (code is not None and str(code) not in {"0", "200", "201"}):
            return False, parsed, _message(parsed), _reference(data)
        return True, parsed, None, _reference(data)
    return True, parsed, None, None


def _message(parsed: Any) -> str:
    if isinstance(parsed, dict):
        return str(parsed.get("message") or parsed.get("error") or "ERP_WRITE_FAILED")[:2000]
    return str(parsed)[:2000]


def _reference(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("operationId", "operation_id", "orderId", "order_id", "id", "orderNumber"):
        value = data.get(key)
        if value is not None:
            return str(value)
    return None
