"""
Task 委派调度服务。

何时派发：主 Agent 提示词（可并行 / 上下文隔离 / 调用链深）。
本模块负责：
  - YAML 注册表校验 ``subagent_type``
  - ``input_context`` 必填：抽取键值写入 ``<delegation-context>``；可自动填则服务端填入
  - 并发上限 / 派发超时
  - 派发 start/end 事件（SSE + 可落库）
  - 回流：sections 结构 + 表格/路径/工具引用证据核验
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..schema import ProcurementContext
from .dispatch_events import publish_dispatch_event


DEFAULT_MIN_DESCRIPTION_CHARS = 24
DEFAULT_MAX_PARALLEL = 4
DEFAULT_DISPATCH_TIMEOUT_S = 180.0

# 视为无效的占位/垃圾值（大小写不敏感 + 原样）
_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "n/a",
        "na",
        "none",
        "null",
        "nil",
        "undefined",
        "未知",
        "待定",
        "暂无",
        "无",
        "xxx",
        "xxxx",
        "...",
        "…",
        "placeholder",
        "tbd",
        "todo",
        "待填",
        "空",
        "-",
        "--",
        "—",
    }
)

# 这些 section 额外要求表格 / 路径 / 工具名引用作证据
_EVIDENCE_SECTIONS = frozenset(
    {
        "evidence",
        "data_table",
        "charts",
        "comparison",
        "risk_assessment",
        "conclusions",
    }
)

_PATH_RE = re.compile(
    r"(?:/workspace|/tmp|/mnt|[\w./\\-]+\.(?:png|jpe?g|svg|csv|md|json|xlsx?|pdf))",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)
_TOOL_REF_RE = re.compile(
    r"`[a-z][a-z0-9_]{2,}`|"
    r"(?:工具|MCP|调用)\s*[`「]?[a-z][a-z0-9_]{2,}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SubAgentRegistry:
    names: frozenset[str]
    configs_by_name: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_configs(cls, configs: list[dict[str, Any]]) -> SubAgentRegistry:
        by_name = {
            str(cfg["name"]): cfg
            for cfg in configs
            if isinstance(cfg, dict) and cfg.get("name")
        }
        return cls(names=frozenset(by_name), configs_by_name=by_name)

    def input_fields(self, subagent_type: str) -> list[dict[str, Any]]:
        cfg = self.configs_by_name.get(subagent_type) or {}
        protocol = cfg.get("context_protocol") or {}
        fields = protocol.get("input_context") or []
        return [f for f in fields if isinstance(f, dict) and f.get("field")]

    def output_sections(self, subagent_type: str) -> list[str]:
        cfg = self.configs_by_name.get(subagent_type) or {}
        output_format = cfg.get("output_format")
        if not isinstance(output_format, dict):
            protocol = cfg.get("context_protocol") or {}
            output_format = protocol.get("output_format") if isinstance(protocol, dict) else None
        if not isinstance(output_format, dict):
            return []
        sections = output_format.get("sections") or []
        return [str(s) for s in sections if isinstance(s, str) and s.strip()]


@dataclass
class DispatchSpan:
    subagent_type: str
    started_at: str
    started_monotonic: float
    description_chars: int
    call_id: str = ""
    filled_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class DispatchOutcome:
    ok: bool
    reason: str = ""
    enriched_description: str = ""
    span: DispatchSpan | None = None
    filled_fields: dict[str, str] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)
    invalid_fields: list[str] = field(default_factory=list)


@dataclass
class VerifyOutcome:
    ok: bool
    missing_sections: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)

    @property
    def failure_labels(self) -> list[str]:
        labels = list(self.missing_sections)
        labels.extend(f"evidence:{s}" for s in self.evidence_gaps)
        return labels


def is_valid_field_value(value: str) -> bool:
    text = (value or "").strip()
    if len(text) < 2:
        return False
    if text.lower() in _PLACEHOLDER_VALUES or text in _PLACEHOLDER_VALUES:
        return False
    if re.fullmatch(r"[.。…\-_=_＊*xX]+", text):
        return False
    return True


def extract_field_value(description: str, field_name: str) -> str | None:
    """从 description 解析 ``field: value``，返回有效值或 None。"""
    if not description or not field_name:
        return None
    patterns = (
        rf"(?im)^[ \t]*{re.escape(field_name)}\s*[：:=]\s*(.+)$",
        rf"(?im)^[ \t]*`{re.escape(field_name)}`\s*[：:=]\s*(.+)$",
        rf"(?im)^[ \t]*\*\*{re.escape(field_name)}\*\*\s*[：:=]\s*(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, description)
        if not match:
            continue
        raw = match.group(1).strip()
        # 同行后续字段截断：foo: a  bar: b
        raw = re.split(r"\s{2,}(?=\w+\s*[：:=])", raw, maxsplit=1)[0].strip()
        raw = raw.strip("`'\"「」")
        if is_valid_field_value(raw):
            return raw
        return None
    return None


def _autofill_value(ctx: ProcurementContext | None, field_name: str) -> str | None:
    if ctx is None:
        return None
    if field_name == "user_id":
        return str(ctx.user_id) if ctx.user_id else None
    if field_name == "username":
        return str(ctx.username) if ctx.username else None
    if field_name == "user_preferences":
        if not ctx.preferences:
            return None
        return json.dumps(ctx.preferences, ensure_ascii=False)
    return None


def extract_filled_and_missing(
    description: str,
    input_fields: list[dict[str, Any]],
    user_context: ProcurementContext | None,
) -> tuple[dict[str, str], list[str], list[str]]:
    """返回（已解析字段值, 缺失必填, 出现键但值无效的字段）。"""
    filled: dict[str, str] = {}
    missing: list[str] = []
    invalid: list[str] = []
    for item in input_fields:
        name = str(item.get("field") or "").strip()
        if not name:
            continue
        required = bool(item.get("required"))
        auto = _autofill_value(user_context, name)
        parsed = extract_field_value(description, name)

        if auto is not None:
            filled[name] = auto
            # description 里显式写了有效值时，以显式为准覆盖（除身份字段可保留 auto）
            if parsed is not None and name not in ("user_id", "username"):
                filled[name] = parsed
            continue

        if parsed is not None:
            filled[name] = parsed
            continue

        # 键出现但值为垃圾
        key_present = bool(
            re.search(
                rf"(?im)^[ \t]*(?:`|\*\*)?{re.escape(name)}(?:`|\*\*)?\s*[：:=]",
                description,
            )
        )
        if key_present:
            invalid.append(name)
            if required:
                missing.append(name)
            continue
        if required:
            missing.append(name)
    return filled, missing, invalid


def _section_body(text: str, section: str) -> str | None:
    header = re.search(
        rf"(?im)^(?:#+\s*{re.escape(section)}\b|"
        rf"\*\*{re.escape(section)}\*\*|"
        rf"\d+\.\s*\*\*{re.escape(section)}\*\*|"
        rf"[ \t]*{re.escape(section)}\s*[：:])"
        rf"[^\n]*\n?(?P<body>.*?)(?=^#+\s|\Z)",
        text or "",
        flags=re.MULTILINE | re.DOTALL,
    )
    if header is None:
        return None
    return (header.group("body") or "").strip()


def _has_evidence(section_body: str) -> bool:
    if _TABLE_RE.search(section_body):
        return True
    if _PATH_RE.search(section_body):
        return True
    if _TOOL_REF_RE.search(section_body):
        return True
    return False


def verify_output_contract(text: str, sections: list[str]) -> VerifyOutcome:
    """结构（sections）+ 证据（表格/路径/工具引用）核验。"""
    if not sections:
        return VerifyOutcome(ok=True)
    missing: list[str] = []
    evidence_gaps: list[str] = []
    body = text or ""
    for section in sections:
        section_body = _section_body(body, section)
        if section_body is None or len(re.sub(r"\s+", "", section_body)) < 2:
            missing.append(section)
            continue
        if section in _EVIDENCE_SECTIONS and not _has_evidence(section_body):
            evidence_gaps.append(section)
    return VerifyOutcome(
        ok=not missing and not evidence_gaps,
        missing_sections=missing,
        evidence_gaps=evidence_gaps,
    )


# 兼容旧名
def verify_output_sections(text: str, sections: list[str]) -> tuple[bool, list[str]]:
    outcome = verify_output_contract(text, sections)
    return outcome.ok, outcome.failure_labels


class TaskDispatchService:
    def __init__(
        self,
        registry: SubAgentRegistry,
        user_context: ProcurementContext | None = None,
        *,
        min_description_chars: int = DEFAULT_MIN_DESCRIPTION_CHARS,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
        timeout_s: float = DEFAULT_DISPATCH_TIMEOUT_S,
    ):
        self._registry = registry
        self._user_context = user_context
        self._min_description_chars = max(1, min_description_chars)
        self._max_parallel = max(1, max_parallel)
        self._timeout_s = max(1.0, float(timeout_s))
        self._active: dict[str, DispatchSpan] = {}

    @property
    def allowed_types(self) -> frozenset[str]:
        return self._registry.names

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    @property
    def max_parallel(self) -> int:
        return self._max_parallel

    @property
    def active_count(self) -> int:
        return len(self._active)

    def validate(
        self,
        subagent_type: str | None,
        description: str | None,
    ) -> tuple[bool, str, dict[str, str], list[str], list[str]]:
        name = (subagent_type or "").strip()
        if not name:
            return False, "task 缺少 subagent_type。", {}, [], []
        if name not in self._registry.names:
            allowed = "、".join(sorted(self._registry.names)) or "(空注册表)"
            return False, f"未知 subagent_type={name!r}；已注册：{allowed}。", {}, [], []

        text = (description or "").strip()
        if not text:
            return False, "task 缺少 description；交接必须自包含。", {}, [], []
        if len(text) < self._min_description_chars:
            return (
                False,
                f"description 过短（{len(text)}<{self._min_description_chars}）。",
                {},
                [],
                [],
            )

        if self.active_count >= self._max_parallel:
            return (
                False,
                f"并发派发已达上限（{self._max_parallel}），请等待进行中的 task 结束后再派。",
                {},
                [],
                [],
            )

        filled, missing, invalid = extract_filled_and_missing(
            text, self._registry.input_fields(name), self._user_context
        )
        if invalid and missing:
            return (
                False,
                "交接字段值无效："
                + "、".join(invalid)
                + "；仍缺必填："
                + "、".join(missing)
                + "。请用「字段名: 有效值」写入 description。",
                filled,
                missing,
                invalid,
            )
        if invalid:
            return (
                False,
                "交接字段值无效（占位/空值）："
                + "、".join(invalid)
                + "。请写入真实业务值。",
                filled,
                missing,
                invalid,
            )
        if missing:
            return (
                False,
                "缺少必填交接字段："
                + "、".join(missing)
                + "。请按「字段名: 值」写入 description（user_id/username 可由服务端注入）。",
                filled,
                missing,
                invalid,
            )
        return True, "", filled, missing, invalid

    def enrich_description(
        self,
        subagent_type: str,
        description: str,
        filled_fields: dict[str, str],
    ) -> str:
        lines = ["<delegation-context>"]
        lines.append(f"subagent_type: {subagent_type}")
        for key in sorted(filled_fields):
            lines.append(f"{key}: {filled_fields[key]}")

        input_fields = self._registry.input_fields(subagent_type)
        required = [
            str(item["field"])
            for item in input_fields
            if item.get("required") and item.get("field")
        ]
        if required:
            lines.append("required_handoff_fields: " + ", ".join(required))
        lines.append("</delegation-context>")
        lines.append("")
        lines.append(description.strip())
        return "\n".join(lines)

    def begin(
        self,
        subagent_type: str,
        description: str,
        call_id: str,
        filled_fields: dict[str, str],
    ) -> DispatchSpan:
        span = DispatchSpan(
            subagent_type=subagent_type,
            started_at=datetime.now(timezone.utc).isoformat(),
            started_monotonic=time.monotonic(),
            description_chars=len(description),
            call_id=call_id,
            filled_fields=dict(filled_fields),
        )
        if call_id:
            self._active[call_id] = span
        event = {
            "type": "agent_dispatch",
            "phase": "start",
            "call_id": call_id,
            "agent": subagent_type,
            "started_at": span.started_at,
            "description_chars": span.description_chars,
            "filled_fields": sorted(filled_fields.keys()),
            "active_parallel": self.active_count,
            "max_parallel": self._max_parallel,
            "timeout_s": self._timeout_s,
        }
        publish_dispatch_event(event)
        return span

    def end(
        self,
        call_id: str,
        *,
        status: str,
        error: str | None = None,
        missing_sections: list[str] | None = None,
        evidence_gaps: list[str] | None = None,
    ) -> dict[str, Any]:
        span = self._active.pop(call_id, None)
        finished_at = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "type": "agent_dispatch",
            "phase": "end",
            "tool": "task",
            "call_id": call_id,
            "status": status,
            "finished_at": finished_at,
            "error": error,
            "missing_sections": missing_sections or [],
            "evidence_gaps": evidence_gaps or [],
            "active_parallel": self.active_count,
        }
        if span is not None:
            payload.update(
                {
                    "agent": span.subagent_type,
                    "started_at": span.started_at,
                    "elapsed_ms": round(
                        (time.monotonic() - span.started_monotonic) * 1000
                    ),
                    "description_chars": span.description_chars,
                    "filled_fields": sorted(span.filled_fields.keys()),
                }
            )
        publish_dispatch_event(payload)
        return payload

    def prepare(
        self,
        subagent_type: str | None,
        description: str | None,
        call_id: str,
    ) -> DispatchOutcome:
        ok, reason, filled, missing, invalid = self.validate(subagent_type, description)
        if not ok:
            return DispatchOutcome(
                ok=False,
                reason=reason,
                filled_fields=filled,
                missing_required=missing,
                invalid_fields=invalid,
            )

        name = (subagent_type or "").strip()
        text = (description or "").strip()
        enriched = self.enrich_description(name, text, filled)
        span = self.begin(name, enriched, call_id, filled)
        return DispatchOutcome(
            ok=True,
            enriched_description=enriched,
            span=span,
            filled_fields=filled,
        )

    def verify_result(self, call_id: str, content: str) -> VerifyOutcome:
        span = self._active.get(call_id)
        if span is None:
            return VerifyOutcome(ok=True)
        sections = self._registry.output_sections(span.subagent_type)
        return verify_output_contract(content, sections)

    def active_subagent(self, call_id: str) -> str | None:
        span = self._active.get(call_id)
        return span.subagent_type if span else None


@dataclass
class GateDecision:
    """中间件可消费的门禁决策（无 langchain 依赖，便于单测）。"""

    action: str  # allow | reject | replace
    reason: str = ""
    enriched_description: str = ""
    replace_content: str = ""
    end_status: str = ""
    missing_sections: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    filled_fields: dict[str, str] = field(default_factory=dict)


class TaskDispatchGate:
    """prepare → 执行 → after_result 生命周期，供中间件与单测共用。"""

    def __init__(self, service: TaskDispatchService):
        self.service = service

    def before_call(
        self,
        subagent_type: str | None,
        description: str | None,
        call_id: str,
    ) -> GateDecision:
        outcome = self.service.prepare(subagent_type, description, call_id)
        if not outcome.ok:
            return GateDecision(
                action="reject",
                reason=outcome.reason,
                filled_fields=outcome.filled_fields,
            )
        return GateDecision(
            action="allow",
            enriched_description=outcome.enriched_description,
            filled_fields=outcome.filled_fields,
        )

    def after_result(
        self,
        call_id: str,
        content: str,
        *,
        is_error: bool = False,
    ) -> GateDecision:
        if is_error:
            self.service.end(call_id, status="error", error=(content or "")[:200])
            return GateDecision(action="allow", end_status="error")

        verified = self.service.verify_result(call_id, content)
        if not verified.ok:
            parts: list[str] = []
            if verified.missing_sections:
                parts.append("缺少 sections：" + "、".join(verified.missing_sections))
            if verified.evidence_gaps:
                parts.append(
                    "缺少证据（表格/路径/工具引用）："
                    + "、".join(verified.evidence_gaps)
                )
            reason = "；".join(parts) + "。请按 output_format 补齐后重新 task。"
            self.service.end(
                call_id,
                status="verification_failed",
                error=reason,
                missing_sections=verified.missing_sections,
                evidence_gaps=verified.evidence_gaps,
            )
            return GateDecision(
                action="replace",
                reason=reason,
                replace_content=f"[委派结果不合格] {reason}",
                end_status="verification_failed",
                missing_sections=verified.missing_sections,
                evidence_gaps=verified.evidence_gaps,
            )

        self.service.end(call_id, status="completed")
        return GateDecision(action="allow", end_status="completed")

    def on_timeout(self, call_id: str) -> GateDecision:
        seconds = int(self.service.timeout_s)
        reason = f"派发超时（>{seconds}s），子 Agent 已中止等待。请缩小任务范围后重试。"
        self.service.end(call_id, status="timeout", error=reason)
        return GateDecision(
            action="replace",
            reason=reason,
            replace_content=f"[委派超时] {reason}",
            end_status="timeout",
        )

    def on_exception(self, call_id: str, exc: BaseException) -> None:
        self.service.end(call_id, status="error", error=str(exc)[:200])
