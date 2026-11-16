"""Persistence for the current full-agent evaluation report schema only."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import EvaluationReport

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH = PROJECT_ROOT / ".runtime" / "evaluation" / "latest_report.json"
REPORT_PATH = Path(os.getenv("EVALUATION_REPORT_PATH", str(DEFAULT_REPORT_PATH)))


def not_run_report() -> dict[str, Any]:
    return {
        "metadata": {
            "report_type": "full_agent_four_dimension_evaluation",
            "schema_version": "2.0",
            "dataset_version": "not-run",
            "git_commit": "unknown",
        },
        "status": "NOT_RUN",
        "metrics": {
            "trajectory": {
                "trajectory_pass_rate": None,
                "tool_call_accuracy": None,
            },
            "business": {
                "task_completion_rate": None,
                "key_fact_accuracy": None,
                "recommendation_feasibility_rate": None,
                "replenishment_quantity_deviation": None,
            },
            "safety": {
                "risk_operation_interception_rate": None,
                "legitimate_write_false_block_rate": None,
            },
            "stability": {
                "pass_3": None,
                "fault_recovery_rate": None,
            },
        },
        "outcomes": {},
        "domains": {},
        "safety_events": {},
        "failure_reasons": {},
        "cases": [],
    }


def load_report(path: Path | None = None) -> dict[str, Any]:
    target = path or REPORT_PATH
    if not target.exists():
        return not_run_report()
    try:
        report = EvaluationReport.model_validate_json(
            target.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise ValueError(f"无效的完整Agent评测报告: {target}") from exc
    return report.model_dump(mode="json")


def dump_report(report: EvaluationReport, path: Path | None = None) -> Path:
    target = path or REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    return target
