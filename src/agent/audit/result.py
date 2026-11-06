"""ResultAuditor：执行结果业务门禁（写声称、失败后假成功、回答字段 ⊆ 工具回执）。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from .payloads import classify_tool_result
from .registry import WRITE_TOOL_SPECS

Severity = Literal["high", "medium", "low"]
Action = Literal["pass", "warn", "reject"]


@dataclass
class AuditFinding:
    code: str
    severity: Severity
    message: str


@dataclass
class AuditResult:
    passed: bool
    action: Action
    findings: list[AuditFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "action": self.action,
            "findings": [asdict(f) for f in self.findings],
        }


@dataclass(frozen=True)
class ToolScan:
    """单次扫描工具回执：成功/失败写工具与可核对字段。"""

    write_outcomes: tuple[tuple[str, bool, str | None], ...]
    receipt_tokens: tuple[str, ...]
    findings: tuple[AuditFinding, ...]


# 写成功声称 ↔ 对应工具族
_WRITE_CLAIM_GROUPS: tuple[tuple[tuple[str, ...], re.Pattern[str]], ...] = (
    (
        ("order_create", "order_update", "order_update_status"),
        re.compile(
            r"(订单(已)?创建成功|已成功(创建|下单)|下单成功|"
            r"订单(已)?(更新|修改)成功|状态(已)?更新成功)"
        ),
    ),
    (
        ("inventory_inbound",),
        re.compile(r"(入库成功|已(成功)?入库|入库完成)"),
    ),
    (
        ("inventory_outbound",),
        re.compile(r"(出库成功|已(成功)?出库|出库完成)"),
    ),
    (
        ("supplier_create", "supplier_update_status"),
        re.compile(
            r"(供应商(已)?创建成功|已成功创建供应商|"
            r"供应商(状态)?(已)?(更新|修改)成功)"
        ),
    ),
    (
        ("part_create",),
        re.compile(r"(零部件(已)?创建成功|已成功创建(零部件|零件)|零件(已)?创建成功)"),
    ),
)

_ORDER_NO_RE = re.compile(
    r"(?:单号|订单号|orderNumber|order_number)\s*[:：#]?\s*([A-Za-z0-9_-]{4,})",
    re.IGNORECASE,
)
_PO_TOKEN_RE = re.compile(r"\bPO[A-Z0-9_-]{4,}\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(
    r"(?:金额|总金额|合计|totalAmount|total_amount)\s*[:：]?\s*"
    r"([0-9]+(?:\.[0-9]+)?)"
    r"|"
    r"([0-9]+(?:\.[0-9]+)?)\s*元",
    re.IGNORECASE,
)

_RECEIPT_TOKEN_KEYS = {
    "ordernumber",
    "order_number",
    "operationid",
    "operation_id",
    "id",
    "orderid",
    "order_id",
    "totalamount",
    "total_amount",
    "unitprice",
    "unit_price",
    "amount",
    "quantity",
}


def _tool_messages(state: dict) -> list[tuple[str, Any]]:
    """返回 (tool_name, parsed_or_raw) 列表。"""
    out: list[tuple[str, Any]] = []
    for m in state.get("messages") or []:
        if getattr(m, "type", "") != "tool":
            continue
        name = getattr(m, "name", "") or ""
        content = getattr(m, "content", "")
        parsed: Any = content
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except (ValueError, TypeError):
                parsed = content
        out.append((name, parsed))
    return out


def _ai_text(state: dict) -> str:
    texts: list[str] = []
    for m in state.get("messages") or []:
        if getattr(m, "type", "") == "ai" and not getattr(m, "tool_calls", None):
            texts.append(str(getattr(m, "content", "") or ""))
    return "\n".join(texts[-3:])


def _normalize_tool_name(name: str) -> str:
    return str(name or "").lower()


def _walk_receipt_tokens(node: Any, out: set[str]) -> None:
    """从工具回执抽取可核对 token（单号、金额等）。"""

    if isinstance(node, dict):
        for key, value in node.items():
            key_l = str(key).lower().replace("-", "_")
            compact = key_l.replace("_", "")
            if compact in _RECEIPT_TOKEN_KEYS or key_l in _RECEIPT_TOKEN_KEYS:
                if value is None or isinstance(value, bool):
                    continue
                if isinstance(value, (int, float, Decimal)):
                    out.add(_money_token(value))
                    out.add(str(value))
                elif isinstance(value, str) and value.strip():
                    out.add(value.strip())
                    try:
                        out.add(_money_token(value))
                    except (InvalidOperation, ValueError):
                        pass
            _walk_receipt_tokens(value, out)
        return
    if isinstance(node, list):
        for item in node:
            _walk_receipt_tokens(item, out)


def _money_token(value: Any) -> str:
    amount = Decimal(str(value))
    return format(amount.quantize(Decimal("0.01")), "f")


def _answer_claim_tokens(answer: str) -> tuple[set[str], set[str]]:
    """返回 (订单号类 token, 金额 token)。"""

    orders: set[str] = set()
    amounts: set[str] = set()
    for match in _ORDER_NO_RE.finditer(answer):
        orders.add(match.group(1))
    for match in _PO_TOKEN_RE.finditer(answer):
        orders.add(match.group(0))
    for match in _AMOUNT_RE.finditer(answer):
        raw = match.group(1) or match.group(2)
        if raw is None:
            continue
        try:
            amounts.add(_money_token(raw))
        except (InvalidOperation, ValueError):
            continue
    return orders, amounts


def scan_tool_results(state: dict) -> ToolScan:
    """扫描工具执行结果，收集写工具成败与回执 token。"""

    outcomes: list[tuple[str, bool, str | None]] = []
    tokens: set[str] = set()
    findings: list[AuditFinding] = []

    for name, parsed in _tool_messages(state):
        tool = _normalize_tool_name(name)
        if tool in WRITE_TOOL_SPECS:
            ok, parsed_obj, err, _ = classify_tool_result(parsed)
            outcomes.append((tool, ok, err))
            if not ok and err:
                findings.append(
                    AuditFinding(
                        "write_tool_error",
                        "medium",
                        f"{tool} 返回业务错误: {err}",
                    )
                )
            if ok:
                _walk_receipt_tokens(parsed_obj, tokens)
        else:
            _walk_receipt_tokens(parsed, tokens)

    return ToolScan(
        write_outcomes=tuple(outcomes),
        receipt_tokens=tuple(sorted(tokens)),
        findings=tuple(findings),
    )


class ResultAuditor:
    """结合工具轨迹做通过/警告/拒绝。

    写操作参数校验由 ERPWriteMiddleware 负责；本类核对宣称与回执。
    """

    def audit(
        self,
        state: dict,
        *,
        tool_scan: ToolScan | None = None,
    ) -> AuditResult:
        findings: list[AuditFinding] = []
        scan = tool_scan or scan_tool_results(state)
        findings.extend(scan.findings)

        answer = _ai_text(state)
        success_by_tool = {
            tool: ok for tool, ok, _ in scan.write_outcomes if ok
        }
        failed_tools = {tool for tool, ok, _ in scan.write_outcomes if not ok}

        for tools, pattern in _WRITE_CLAIM_GROUPS:
            if not answer or not pattern.search(answer):
                continue
            group_failed = [t for t in tools if t in failed_tools]
            group_ok = any(t in success_by_tool for t in tools)
            if group_failed and not group_ok:
                findings.append(
                    AuditFinding(
                        "claim_after_write_failure",
                        "high",
                        f"回答声称写操作成功，但工具失败: {', '.join(group_failed)}",
                    )
                )
            elif not group_ok:
                findings.append(
                    AuditFinding(
                        "write_claim_without_tool",
                        "high",
                        f"回答声称写操作成功，但轨迹中无成功回执（期望工具: {', '.join(tools)}）",
                    )
                )

        findings.extend(self._audit_answer_subset(answer, set(scan.receipt_tokens)))

        high = [f for f in findings if f.severity == "high"]
        if high:
            action: Action = "reject"
            passed = False
        elif findings:
            action = "warn"
            passed = True
        else:
            action = "pass"
            passed = True

        return AuditResult(passed=passed, action=action, findings=findings)

    def _audit_answer_subset(
        self, answer: str, receipt_tokens: set[str]
    ) -> list[AuditFinding]:
        if not answer:
            return []
        orders, amounts = _answer_claim_tokens(answer)
        if not orders and not amounts:
            return []

        receipt_upper = {t.upper() for t in receipt_tokens}
        receipt_money = {t for t in receipt_tokens if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", t)}
        findings: list[AuditFinding] = []

        for token in sorted(orders):
            if token.upper() not in receipt_upper and token not in receipt_tokens:
                findings.append(
                    AuditFinding(
                        "answer_value_not_in_receipt",
                        "high",
                        f"回答中的订单号/业务号 {token} 不在工具回执字段中",
                    )
                )

        for token in sorted(amounts):
            if token not in receipt_money and token not in receipt_tokens:
                findings.append(
                    AuditFinding(
                        "answer_value_not_in_receipt",
                        "high",
                        f"回答中的金额 {token} 不在工具回执字段中",
                    )
                )
        return findings
