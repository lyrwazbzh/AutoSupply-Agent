"""ResultAuditor：执行结果业务门禁"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from ..shortage.records import load_calc_result, persist_calc_record

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
    calc_run_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "action": self.action,
            "findings": [asdict(f) for f in self.findings],
            "calc_run_ids": self.calc_run_ids,
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


def _human_text(state: dict) -> str:
    """Return the current user request for evidence-only audit checks."""
    texts: list[str] = []
    for m in state.get("messages") or []:
        if getattr(m, "type", "") == "human":
            texts.append(str(getattr(m, "content", "") or ""))
    return "\n".join(texts[-2:])


def _extract_calc_payload(parsed: Any) -> Optional[dict]:
    if not isinstance(parsed, dict):
        return None
    data = parsed.get("data") if "data" in parsed else parsed
    if isinstance(data, dict) and data.get("calc_run_id"):
        return data
    return None


class ResultAuditor:
    """结合工具轨迹与计算快照做通过/警告/拒绝。"""

    WRITE_TOOLS = (
        "order_create",
        "order_update",
        "inventory_inbound",
        "inventory_outbound",
    )

    def __init__(self, *, store: Any = None, user_id: str = "default_user"):
        self.store = store
        self.user_id = user_id

    def audit(self, state: dict) -> AuditResult:
        findings: list[AuditFinding] = []
        if state.get("snapshot_persistence_error"):
            findings.append(
                AuditFinding(
                    "calc_record_persistence_failed",
                    "high",
                    f"不可变计算记录持久化失败: {state['snapshot_persistence_error']}",
                )
            )
        calc_ids: list[str] = []
        snapshots: dict[str, dict] = dict(state.get("calc_snapshots") or {})

        # 新会话可通过持久化 calc_run_id 恢复，不依赖同一个 Graph State。
        referenced_ids = set(re.findall(r"calc_run_id\s*[=:：]\s*([\w.-]+)", _ai_text(state)))
        for fact in state.get("business_facts") or []:
            if isinstance(fact, dict) and fact.get("calc_run_id"):
                referenced_ids.add(str(fact["calc_run_id"]))
        for run_id in referenced_ids:
            if run_id not in snapshots:
                persisted = load_calc_result(self.store, self.user_id, run_id)
                if persisted:
                    snapshots[run_id] = persisted

        tool_rows = _tool_messages(state)
        for name, parsed in tool_rows:
            if "shortage_calc" in name.lower():
                payload = _extract_calc_payload(parsed)
                if payload:
                    rid = str(payload["calc_run_id"])
                    calc_ids.append(rid)
                    snapshots[rid] = payload
                elif isinstance(parsed, dict) and parsed.get("code") not in (200, None, "200"):
                    findings.append(
                        AuditFinding(
                            "shortage_calc_failed",
                            "high",
                            "shortage_calc 未成功返回计算结果",
                        )
                    )

            # 写工具回执粗检
            if any(w in name.lower() for w in ("order_create", "order_update")):
                findings.extend(self._audit_order_payload(name, parsed))

        # 写前参数：从 AI tool_calls 细校验（与 WriteGuard 口径对齐）
        findings.extend(self._audit_write_tool_calls(state))

        answer = _ai_text(state)
        request_text = _human_text(state)
        shortage_requested = bool(
            re.search(r"缺料|缺口|齐套|短缺|补货建议|shortage", request_text, re.I)
            or any("shortage_calc" in name.lower() for name, _ in tool_rows)
        )

        # 缺料结论：只根据请求和执行证据校验，不依赖额外的路由状态。
        if shortage_requested and not calc_ids and not snapshots:
            if len(answer) > 80 and re.search(r"缺口|齐套|建议量|缺料", answer):
                findings.append(
                    AuditFinding(
                        "shortage_without_calc",
                        "high",
                        "缺料结论未绑定 shortage_calc / calc_run_id",
                    )
                )

        # 数值 ⊆ 最近一次 calc；业务口径和来源由计算记录自身提供
        if snapshots and (
            re.search(r"缺口|齐套|建议", answer)
            or state.get("business_facts")
        ):
            latest = snapshots[calc_ids[-1]] if calc_ids else next(iter(snapshots.values()))
            findings.extend(self._audit_numbers_against_calc(answer, latest))
            findings.extend(self._audit_caliber(latest))
            findings.extend(
                self.audit_facts(state.get("business_facts") or [], latest)
            )

        # 声称下单成功但无写工具成功回执
        if re.search(r"(订单(已)?创建成功|已成功(创建|下单)|下单成功)", answer):
            write_ok = False
            for name, parsed in tool_rows:
                if any(w in name.lower() for w in self.WRITE_TOOLS):
                    if isinstance(parsed, dict) and parsed.get("code") in (200, "200", None):
                        if parsed.get("code") == 200 or parsed.get("data") or "success" in str(parsed).lower():
                            write_ok = True
                    elif isinstance(parsed, str) and "成功" in parsed:
                        write_ok = True
            if not write_ok:
                findings.append(
                    AuditFinding(
                        "write_claim_without_tool",
                        "high",
                        "回答声称写单成功但轨迹中无成功的写工具回执",
                    )
                )

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

        return AuditResult(
            passed=passed,
            action=action,
            findings=findings,
            calc_run_ids=calc_ids or list(snapshots.keys()),
        )

    def collect_snapshots(self, state: dict) -> dict[str, dict]:
        """从工具消息收集 calc 快照，供写入 checkpoint。"""
        snaps = dict(state.get("calc_snapshots") or {})
        for name, parsed in _tool_messages(state):
            if "shortage_calc" not in name.lower():
                continue
            payload = _extract_calc_payload(parsed)
            if payload:
                snaps[str(payload["calc_run_id"])] = payload
        return snaps

    def persist_snapshots(self, snapshots: dict[str, dict]) -> list[str]:
        """将工具返回的完整 CalcRecord 写入现有 Store，重复内容幂等、冲突拒绝。"""

        persisted: list[str] = []
        if self.store is None:
            return persisted
        for run_id, payload in snapshots.items():
            record = payload.get("calc_record") if isinstance(payload, dict) else None
            if not isinstance(record, dict):
                if isinstance(payload, dict) and payload.get("caliber_version") == "shortage-口径/v2":
                    raise ValueError(f"calc_run_id={run_id} 的 v2 结果缺少 calc_record")
                continue
            persist_calc_record(self.store, self.user_id, record)
            persisted.append(str(run_id))
        return persisted

    def _audit_order_payload(self, name: str, parsed: Any) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        if isinstance(parsed, dict) and parsed.get("code") not in (None, 200, "200"):
            findings.append(
                AuditFinding(
                    "order_tool_error",
                    "medium",
                    f"{name} 返回业务错误: {parsed.get('message', parsed.get('code'))}",
                )
            )
        return findings

    def _audit_write_tool_calls(self, state: dict) -> list[AuditFinding]:
        from ..shortage.suggestion import (
            assert_payload_matches_calc,
            parse_order_data_arg,
            validate_order_create_payload,
        )

        findings: list[AuditFinding] = []
        snaps = state.get("calc_snapshots") or {}
        for m in state.get("messages") or []:
            for call in getattr(m, "tool_calls", []) or []:
                name = (call.get("name") or "").lower()
                if name not in ("order_create", "order_update"):
                    continue
                args = call.get("args") or {}
                raw = args.get("order_data", args)
                try:
                    data = parse_order_data_arg(raw)
                except Exception as e:
                    findings.append(
                        AuditFinding("order_args_parse", "high", f"order_data 解析失败: {e}")
                    )
                    continue
                for err in validate_order_create_payload(data):
                    findings.append(AuditFinding("order_field_invalid", "high", err))
                rid = data.get("calc_run_id")
                if rid:
                    calc = snaps.get(str(rid)) or load_calc_result(
                        self.store, self.user_id, str(rid)
                    )
                    for err in assert_payload_matches_calc(data, calc):
                        findings.append(AuditFinding("order_calc_mismatch", "high", err))
        return findings

    def _audit_caliber(self, calc: dict) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        caliber = calc.get("caliber_version") or calc.get("caliber")
        if not caliber:
            findings.append(
                AuditFinding(
                    "missing_caliber_version",
                    "medium",
                    "计算结果缺少 caliber_version，无法溯源口径",
                )
            )
        return findings

    def _audit_numbers_against_calc(self, answer: str, calc: dict) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        lines = calc.get("lines") or []
        metric_patterns = {
            "net_gap": r"(?:净?缺口|缺少)\s*(?:为|是|[：:=|])*\s*(\d+(?:\.\d+)?)",
            "suggested_qty": r"(?:建议采购量|建议量|补货量)\s*(?:为|是|[：:=|])*\s*(\d+(?:\.\d+)?)",
            "demand_qty": r"(?:需求量|计划需求)\s*(?:为|是|[：:=|])*\s*(\d+(?:\.\d+)?)",
            "supply_qty": r"(?:可用供给|供给量)\s*(?:为|是|[：:=|])*\s*(\d+(?:\.\d+)?)",
            "on_hand": r"(?:现有库存|库存量)\s*(?:为|是|[：:=|])*\s*(\d+(?:\.\d+)?)",
            "in_transit": r"(?:有效在途|在途量)\s*(?:为|是|[：:=|])*\s*(\d+(?:\.\d+)?)",
        }
        segments = [segment.strip() for segment in re.split(r"[\n。；;]+", answer) if segment.strip()]
        for segment in segments:
            matched_lines = []
            for line in lines:
                aliases = [
                    str(line.get("part_name") or ""),
                    str(line.get("part_code") or ""),
                    f"part_id={line.get('part_id')}",
                    f"物料{line.get('part_id')}",
                ]
                if any(alias and alias in segment for alias in aliases):
                    matched_lines.append(line)
            for metric, pattern in metric_patterns.items():
                for match in re.finditer(pattern, segment):
                    actual = Decimal(match.group(1))
                    if matched_lines:
                        for line in matched_lines:
                            expected = Decimal(str(line.get(metric)))
                            if actual != expected:
                                findings.append(
                                    AuditFinding(
                                        "business_fact_mismatch",
                                        "high",
                                        f"物料 {line.get('part_code') or line.get('part_id')} 的 {metric}={actual}，"
                                        f"与 calc_run_id={calc.get('calc_run_id')} 中的 {expected} 不一致",
                                    )
                                )
                    else:
                        # 未指明物料时也只允许与同一指标比对，禁止跨字段“撞数字”。
                        allowed = {Decimal(str(line.get(metric))) for line in lines if line.get(metric) is not None}
                        if actual not in allowed:
                            findings.append(
                                AuditFinding(
                                    "metric_value_not_in_calc",
                                    "high",
                                    f"回答中的 {metric}={actual} 未在该批次同名指标中找到",
                                )
                            )

        for match in re.finditer(r"齐套率\s*[：:=]?\s*(\d+(?:\.\d+)?)\s*(%)?", answer):
            actual = Decimal(match.group(1))
            expected = Decimal(str(calc.get("kit_rate")))
            if match.group(2):
                expected *= Decimal(100)
            if actual != expected:
                findings.append(
                    AuditFinding("kit_rate_mismatch", "high", f"齐套率 {actual} 与 calc 中的 {expected} 不一致")
                )
        if calc.get("calc_run_id") and str(calc["calc_run_id"]) not in answer:
            findings.append(
                AuditFinding(
                    "missing_calc_run_id",
                    "medium",
                    "缺料分析未在回答中引用 calc_run_id",
                )
            )
        return findings

    def audit_facts(self, facts: list[dict[str, Any]], calc: dict) -> list[AuditFinding]:
        """核验结构化五元组 ``(run, part, metric, unit, value)``。"""

        findings: list[AuditFinding] = []
        if not facts:
            return findings
        by_part = {str(line.get("part_id")): line for line in calc.get("lines") or []}
        metric_fields = {
            "net_gap", "suggested_qty", "demand_qty", "supply_qty", "on_hand",
            "in_transit", "allocated", "gap_amount", "suggested_amount",
        }
        unit_aliases = {"piece": "件", "pieces": "件", "pcs": "件", "个": "个", "件": "件"}
        for index, fact in enumerate(facts):
            if not isinstance(fact, dict):
                findings.append(AuditFinding("invalid_business_fact", "high", f"business_facts[{index}] 不是对象"))
                continue
            if str(fact.get("calc_run_id")) != str(calc.get("calc_run_id")):
                findings.append(AuditFinding("fact_calc_mismatch", "high", f"business_facts[{index}] calc_run_id 不一致"))
                continue
            metric = str(fact.get("metric") or "")
            if metric == "kit_rate":
                expected = calc.get("kit_rate")
                line = None
            else:
                if metric not in metric_fields:
                    findings.append(AuditFinding("invalid_fact_metric", "high", f"business_facts[{index}] 指标 {metric} 不受支持"))
                    continue
                line = by_part.get(str(fact.get("part_id")))
                if line is None:
                    findings.append(AuditFinding("fact_part_missing", "high", f"business_facts[{index}] 物料不在 calc 中"))
                    continue
                expected = line.get(metric)
            try:
                actual_value = Decimal(str(fact.get("value")))
                expected_value = Decimal(str(expected))
                if metric == "kit_rate" and str(fact.get("unit") or "").lower() in ("%", "percent"):
                    expected_value *= Decimal(100)
                if actual_value != expected_value:
                    findings.append(AuditFinding("fact_value_mismatch", "high", f"business_facts[{index}] 数值 {actual_value} ≠ {expected_value}"))
            except (InvalidOperation, TypeError):
                findings.append(AuditFinding("invalid_fact_value", "high", f"business_facts[{index}] value 不是有效数值"))
            if line is not None and fact.get("unit"):
                actual_unit = unit_aliases.get(str(fact["unit"]).lower(), str(fact["unit"]).lower())
                expected_unit = unit_aliases.get(str(line.get("unit") or "").lower(), str(line.get("unit") or "").lower())
                if expected_unit and actual_unit != expected_unit:
                    findings.append(AuditFinding("fact_unit_mismatch", "high", f"business_facts[{index}] 单位 {fact['unit']} ≠ {line.get('unit')}"))
        return findings
