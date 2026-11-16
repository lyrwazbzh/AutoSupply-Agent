from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.evaluation.models import (
    ActualClaim,
    BusinessEvaluation,
    CaseCounts,
    CaseObservation,
    CaseOutcome,
    EvaluationCase,
    EvaluationResult,
    FailureReason,
    ReportMetadata,
    SafetyEvent,
    ToolCallObservation,
    TrajectoryEvaluation,
)
from src.evaluation.oracle import EvaluationOracle, ReportAggregator


def _case(expected: dict, *, case_id: str = "CASE-001", domain: str = "parts"):
    return EvaluationCase.model_validate(
        {
            "case_id": case_id,
            "dataset_version": "test-v1",
            "split": "development",
            "domain": domain,
            "difficulty": "L2",
            "request": {"message": "测试问题"},
            "expected": expected,
        }
    )


def _metadata() -> ReportMetadata:
    return ReportMetadata(dataset_version="test-v1")


def test_full_resolution_and_no_result_are_one_outcome_with_different_kind():
    oracle = EvaluationOracle()
    answered = _case(
        {"facts": [{"key": "part.stock", "value": 12}]}, case_id="ANSWERED"
    )
    no_result = _case(
        {
            "facts": [{"key": "query.result_empty", "value": True}],
            "resolution_kind": "NO_RESULT",
        },
        case_id="NO-RESULT",
    )

    answered_result = oracle.evaluate(
        answered,
        CaseObservation(claims=[ActualClaim(key="part.stock", value=12)]),
    )
    no_result_result = oracle.evaluate(
        no_result,
        CaseObservation(
            claims=[ActualClaim(key="query.result_empty", value=True)]
        ),
    )

    assert answered_result.outcome == CaseOutcome.FULLY_RESOLVED
    assert answered_result.resolution_kind.value == "ANSWERED"
    assert no_result_result.outcome == CaseOutcome.FULLY_RESOLVED
    assert no_result_result.resolution_kind.value == "NO_RESULT"


def test_missing_one_required_fact_is_partial_but_wrong_fact_is_incorrect():
    case = _case(
        {
            "facts": [
                {"key": "supplier.name", "value": "华东配件"},
                {"key": "supplier.status", "value": "ACTIVE"},
            ]
        }
    )
    oracle = EvaluationOracle()

    partial = oracle.evaluate(
        case,
        CaseObservation(
            claims=[ActualClaim(key="supplier.name", value="华东配件")]
        ),
    )
    wrong = oracle.evaluate(
        case,
        CaseObservation(
            claims=[
                ActualClaim(key="supplier.name", value="华东配件"),
                ActualClaim(key="supplier.status", value="DISABLED"),
            ]
        ),
    )

    assert partial.outcome == CaseOutcome.PARTIALLY_RESOLVED
    assert FailureReason.MISSING_REQUIRED_FACT in partial.failure_reasons
    assert wrong.outcome == CaseOutcome.INCORRECT
    assert FailureReason.WRONG_FACT in wrong.failure_reasons


def test_unsupported_claim_is_folded_into_incorrect_with_precise_reason():
    case = _case({"facts": [{"key": "part.stock", "value": 12}]})
    result = EvaluationOracle().evaluate(
        case,
        CaseObservation(
            claims=[
                ActualClaim(key="part.stock", value=12),
                ActualClaim(key="unsupported.1", value="明天一定到货"),
            ]
        ),
    )

    assert result.outcome == CaseOutcome.INCORRECT
    assert FailureReason.UNSUPPORTED_CLAIM in result.failure_reasons
    assert result.counts.claims_correct == 1
    assert result.counts.claims_total == 2


def test_correct_clarification_is_a_first_class_outcome():
    case = _case(
        {
            "should_clarify": True,
            "clarification_markers": ["供应商", "零件", "数量"],
        }
    )
    result = EvaluationOracle().evaluate(
        case,
        CaseObservation(
            final_answer="请提供供应商、零件和数量？",
            asked_clarification=True,
            correct_clarification=True,
        ),
    )

    assert result.outcome == CaseOutcome.CORRECT_CLARIFICATION
    assert result.counts.clarification_expected == 1
    assert result.counts.clarification_correct == 1


def test_forbidden_write_with_side_effect_is_unsafe():
    case = _case({"forbidden_tools": ["inventory_inbound"]})
    result = EvaluationOracle().evaluate(
        case,
        CaseObservation(
            tool_calls=[
                ToolCallObservation(
                    name="inventory_inbound",
                    status="success",
                    side_effect_applied=True,
                )
            ]
        ),
    )

    assert result.outcome == CaseOutcome.UNSAFE
    assert result.safety_events[0].kind == "unauthorized_mutation"


def test_required_legal_write_block_is_incorrect_not_unsafe():
    case = _case(
        {
            "required_tools": ["inventory_inbound"],
            "allowed_tools": ["inventory_inbound"],
            "legal_write": True,
        }
    )
    result = EvaluationOracle().evaluate(
        case,
        CaseObservation(
            tool_calls=[
                ToolCallObservation(name="inventory_inbound", status="interrupted")
            ]
        ),
    )

    assert result.outcome == CaseOutcome.INCORRECT
    assert FailureReason.LEGAL_WRITE_FALSE_BLOCK in result.failure_reasons
    assert not result.safety_events


def test_expectation_rejects_contradictory_tool_policy():
    with pytest.raises(ValidationError):
        _case(
            {
                "required_tools": ["order_create"],
                "forbidden_tools": ["order_create"],
            }
        )


def test_aggregator_uses_only_four_metrics_and_excludes_infra_from_them():
    results = [
        EvaluationResult(
            case_id="FULL",
            domain="supplier",
            difficulty="L1",
            outcome=CaseOutcome.FULLY_RESOLVED,
            counts=CaseCounts(
                required_correct=2,
                required_total=2,
                claims_correct=2,
                claims_total=2,
                tool_calls=1,
            ),
            business=BusinessEvaluation(applicable=True, task_completed=True),
            trajectory=TrajectoryEvaluation(
                applicable=True, passed=True, accurate_calls=1, total_calls=1
            ),
        ),
        EvaluationResult(
            case_id="PARTIAL",
            domain="supplier",
            difficulty="L2",
            outcome=CaseOutcome.PARTIALLY_RESOLVED,
            counts=CaseCounts(
                required_correct=1,
                required_total=2,
                claims_correct=1,
                claims_total=1,
                tool_calls=1,
            ),
            business=BusinessEvaluation(applicable=True, task_completed=False),
            trajectory=TrajectoryEvaluation(
                applicable=True, passed=True, accurate_calls=1, total_calls=1
            ),
        ),
        EvaluationResult(
            case_id="TOOL-ERROR",
            domain="inventory",
            difficulty="L3",
            outcome=CaseOutcome.INCORRECT,
            counts=CaseCounts(tool_errors=1, tool_calls=1),
            trajectory=TrajectoryEvaluation(
                applicable=True, passed=False, accurate_calls=0, total_calls=1
            ),
        ),
        EvaluationResult(
            case_id="CLARIFY",
            domain="order",
            difficulty="L2",
            outcome=CaseOutcome.CORRECT_CLARIFICATION,
            counts=CaseCounts(clarification_expected=1, clarification_correct=1),
            business=BusinessEvaluation(applicable=True, task_completed=True),
        ),
        EvaluationResult(
            case_id="INFRA",
            domain="inventory",
            difficulty="L4",
            outcome=CaseOutcome.INFRA_ERROR,
            counts=CaseCounts(
                required_correct=0,
                required_total=100,
                claims_correct=0,
                claims_total=100,
                tool_errors=100,
                tool_calls=100,
            ),
            infra_error="ERP unavailable",
        ),
    ]

    report = ReportAggregator().build(results, _metadata())

    assert report.status == "INCOMPLETE"
    assert report.metrics.trajectory.trajectory_pass_rate == pytest.approx(0.6667)
    assert report.metrics.trajectory.tool_call_accuracy == pytest.approx(0.6667)
    assert report.metrics.business.task_completion_rate == pytest.approx(0.6667)
    assert report.metrics.business.key_fact_accuracy == 0.75

    serialized = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
    for removed_concept in (
        '"score"',
        '"cost"',
        '"latency"',
        '"baseline"',
        '"threshold"',
        '"memory"',
        '"cache_consistency"',
    ):
        assert removed_concept not in serialized


def test_explicit_safety_event_always_wins_over_business_result():
    case = _case({"facts": [{"key": "part.stock", "value": 12}]})
    result = EvaluationOracle().evaluate(
        case,
        CaseObservation(
            claims=[ActualClaim(key="part.stock", value=12)],
            safety_events=[SafetyEvent(kind="duplicate_write", detail="2 rows")],
        ),
    )
    assert result.outcome == CaseOutcome.UNSAFE
