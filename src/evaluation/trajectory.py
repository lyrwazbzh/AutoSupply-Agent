"""Executable trajectory-contract evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from .matching import argument_matches
from .models import (
    FailureReason,
    OrderConstraint,
    ToolActionExpectation,
    ToolCallObservation,
    TrajectoryContract,
    TrajectoryEvaluation,
)


@dataclass
class _PathResult:
    passed: bool
    accurate_calls: int
    total_calls: int
    positions: dict[str, list[int]]
    diagnostics: list[str]


def _match_actions(
    actions: list[ToolActionExpectation],
    order: list[OrderConstraint],
    calls: list[ToolCallObservation],
) -> _PathResult:
    unused = set(range(len(calls)))
    positions: dict[str, list[int]] = {}
    diagnostics: list[str] = []
    expected_slots = sum(action.min_calls for action in actions)
    accurate_calls = 0

    for action in actions:
        candidates = [
            index
            for index in sorted(unused)
            if calls[index].name in action.tools
            and all(
                argument_matches(constraint, calls[index].arguments)
                for constraint in action.arguments
            )
        ]
        selected = candidates[: action.min_calls]
        positions[action.action_id] = selected
        accurate_calls += len(selected)
        unused.difference_update(selected)
        if len(selected) < action.min_calls:
            same_tool = [call for call in calls if call.name in action.tools]
            if same_tool and action.arguments:
                diagnostics.append(f"动作 {action.action_id} 参数不匹配")
            else:
                diagnostics.append(f"缺少动作 {action.action_id}")
        if any(calls[index].status == "interrupted" for index in selected):
            diagnostics.append(f"动作 {action.action_id} 未完成")
        matching_tool_count = sum(call.name in action.tools for call in calls)
        if action.max_calls is not None and matching_tool_count > action.max_calls:
            diagnostics.append(f"动作 {action.action_id} 调用次数超限")

    for constraint in order:
        before = positions.get(constraint.before, [])
        after = positions.get(constraint.after, [])
        if not before or not after or max(before) >= min(after):
            diagnostics.append(
                f"动作顺序不满足 {constraint.before} -> {constraint.after}"
            )

    total_calls = max(expected_slots, len(calls))
    return _PathResult(
        passed=not diagnostics,
        accurate_calls=accurate_calls,
        total_calls=total_calls,
        positions=positions,
        diagnostics=diagnostics,
    )


class TrajectoryEvaluator:
    def evaluate(
        self,
        contract: TrajectoryContract | None,
        calls: list[ToolCallObservation],
        harness_trace: list[dict] | None = None,
    ) -> tuple[TrajectoryEvaluation, set[FailureReason]]:
        if contract is None:
            return TrajectoryEvaluation(), set()

        considered = [call for call in calls if call.error_source != "infra"]
        base = _match_actions(contract.required_actions, contract.order, considered)
        candidates: list[tuple[str | None, _PathResult]] = [(None, base)]
        if contract.alternative_paths:
            candidates = []
            for path in contract.alternative_paths:
                candidate = _match_actions(
                    [*contract.required_actions, *path.actions],
                    [*contract.order, *path.order],
                    considered,
                )
                candidates.append((path.path_id, candidate))

        matched_path, best = max(
            candidates,
            key=lambda item: (
                item[1].passed,
                item[1].accurate_calls,
                -len(item[1].diagnostics),
            ),
        )
        diagnostics = list(best.diagnostics)
        forbidden = sorted(
            {call.name for call in considered if call.name in contract.forbidden_tools}
        )
        if forbidden:
            diagnostics.append("调用禁止工具: " + ", ".join(forbidden))
        unexpected = sorted(
            {
                call.name
                for call in considered
                if contract.allowed_tools and call.name not in contract.allowed_tools
            }
        )
        if unexpected:
            diagnostics.append("调用契约外工具: " + ", ".join(unexpected))
        if any(call.counts_as_agent_error for call in considered):
            diagnostics.append("工具调用存在参数或调用错误")

        phases = [
            str(item.get("phase"))
            for item in (harness_trace or [])
            if item.get("type") == "phase" and item.get("phase")
        ]
        missing_phases = [
            phase for phase in contract.required_phases if phase not in phases
        ]
        if missing_phases:
            diagnostics.append("缺少Harness阶段: " + ", ".join(missing_phases))
        if contract.phase_order:
            cursor = 0
            for phase in phases:
                if cursor < len(contract.phase_order) and phase == contract.phase_order[cursor]:
                    cursor += 1
            if cursor != len(contract.phase_order):
                diagnostics.append(
                    "Harness阶段顺序不满足: " + " -> ".join(contract.phase_order)
                )

        passed = not diagnostics
        reasons: set[FailureReason] = set()
        if diagnostics:
            reasons.add(FailureReason.WRONG_TOOL_FLOW)
        if any("参数不匹配" in item for item in diagnostics):
            reasons.add(FailureReason.WRONG_TOOL_ARGUMENT)
        if any("动作顺序" in item for item in diagnostics):
            reasons.add(FailureReason.WRONG_TOOL_ORDER)
        return (
            TrajectoryEvaluation(
                applicable=True,
                passed=passed,
                accurate_calls=best.accurate_calls,
                total_calls=best.total_calls,
                matched_path=matched_path,
                diagnostics=diagnostics,
            ),
            reasons,
        )
