"""Cross-trial stability aggregation."""

from __future__ import annotations

from collections import defaultdict

from .models import EvaluationResult, StabilityMetrics


def stability_metrics(results: list[EvaluationResult]) -> StabilityMetrics:
    by_case: dict[str, list[EvaluationResult]] = defaultdict(list)
    for result in results:
        by_case[result.case_id].append(result)

    pass3_values: list[bool] = []
    for trials in by_case.values():
        ordered = sorted(trials, key=lambda item: item.trial_index)
        if len(ordered) >= 3:
            pass3_values.append(all(item.passed for item in ordered[:3]))

    fault_trials = [item for item in results if item.stability.fault_injected]
    recovered = [
        item
        for item in fault_trials
        if item.stability.fault_recovered is True and item.passed
    ]
    return StabilityMetrics(
        pass_3=(
            round(sum(pass3_values) / len(pass3_values), 4)
            if pass3_values
            else None
        ),
        fault_recovery_rate=(
            round(len(recovered) / len(fault_trials), 4)
            if fault_trials
            else None
        ),
    )
