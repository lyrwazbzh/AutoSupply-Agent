"""Four-dimension full-agent evaluation contracts and deterministic oracles."""

from .models import (
    ActualClaim,
    CaseObservation,
    CaseOutcome,
    EvaluationCase,
    EvaluationMetrics,
    EvaluationReport,
    EvaluationResult,
    EvaluationSuite,
    FailureReason,
    ResolutionKind,
    SafetyEvent,
    ToolCallObservation,
)
from .oracle import EvaluationOracle, ReportAggregator

__all__ = [
    "ActualClaim",
    "CaseObservation",
    "CaseOutcome",
    "EvaluationCase",
    "EvaluationMetrics",
    "EvaluationOracle",
    "EvaluationReport",
    "EvaluationResult",
    "EvaluationSuite",
    "FailureReason",
    "ReportAggregator",
    "ResolutionKind",
    "SafetyEvent",
    "ToolCallObservation",
]
