"""Result 阶段业务门禁：核对最终回答与工具回执（≠ ERP 写路径治理）。

挂在 SafeRubric 之前注册，使 after_agent 逆序为：
ReviewExecutionGate → SafeRubric → ResultAudit → … → HarnessPhase。
"""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, Runtime
from typing_extensions import NotRequired

from ..audit.result import ResultAuditor, scan_tool_results
from ..harness import HarnessPhaseState
from ..schema import ReviewResult


class ResultAuditState(HarnessPhaseState):
    audit_result: NotRequired[dict]


class ResultAuditMiddleware(AgentMiddleware):
    """一轮执行结束后的结果审计（假写声称、失败后假成功、回答 ⊆ 回执）。"""

    state_schema = ResultAuditState

    def __init__(self, *, store=None, user_id: str = "default_user"):
        # store / user_id 保留以兼容组装处传参；本门禁不再依赖 Store。
        self._store = store
        self._user_id = user_id or "default_user"
        self.tools = []

    @property
    def name(self) -> str:
        return "ResultAuditMiddleware"

    def after_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        updates: dict[str, Any] = {}
        auditor = ResultAuditor()
        tool_scan = scan_tool_results(state)
        audit = auditor.audit(state, tool_scan=tool_scan)
        updates["audit_result"] = audit.to_dict()

        status = state.get("_rubric_status") if state.get("rubric") else None
        if audit.action == "reject" and status not in (
            "max_iterations_reached",
            "failed",
        ):
            status = "needs_revision" if state.get("rubric") else "failed"
            if state.get("rubric"):
                updates["_rubric_status"] = "needs_revision"

        if status and audit.action == "reject":
            evaluations = state.get("_rubric_evaluations") or []
            last = evaluations[-1] if evaluations else {}
            explanation = last.get("explanation", "")
            audit_msg = "; ".join(
                f.message for f in audit.findings if f.severity == "high"
            ) or "; ".join(f.message for f in audit.findings)
            explanation = (explanation + " | " if explanation else "") + audit_msg
            updates["review_result"] = ReviewResult(
                verdict=status,
                explanation=explanation,
                criteria=[dict(c) for c in last.get("criteria", [])],
                iteration=last.get("iteration", 0),
            ).model_dump()
        elif audit.action == "reject" and not state.get("rubric"):
            updates["review_result"] = ReviewResult(
                verdict="failed",
                explanation="; ".join(f.message for f in audit.findings),
                criteria=[],
                iteration=0,
            ).model_dump()

        return updates or None
