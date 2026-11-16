"""Business-quality evaluation grounded in claims and ERP state."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from .matching import MISSING, assess_state, decimal_value, fact_matches, lookup_path
from .models import (
    ActualClaim,
    BusinessEvaluation,
    BusinessExpectation,
    CaseObservation,
    ExpectedFact,
    FactAssessment,
    FailureReason,
)


def _assess_facts(
    facts: list[ExpectedFact], claims: list[ActualClaim]
) -> tuple[list[FactAssessment], int, int, int, int, set[FailureReason]]:
    facts_by_key: dict[str, list[ExpectedFact]] = defaultdict(list)
    claims_by_key: dict[str, list[ActualClaim]] = defaultdict(list)
    for fact in facts:
        facts_by_key[fact.key].append(fact)
    for claim in claims:
        claims_by_key[claim.key].append(claim)

    assessments: list[FactAssessment] = []
    reasons: set[FailureReason] = set()
    required_total = sum(fact.required for fact in facts)
    required_correct = 0
    for fact in facts:
        matching_claim = next(
            (
                claim
                for claim in claims_by_key.get(fact.key, [])
                if fact_matches(fact, claim.value)
            ),
            None,
        )
        correct = matching_claim is not None
        if fact.required and correct:
            required_correct += 1
        assessments.append(
            FactAssessment(
                key=fact.key,
                expected=fact.value,
                actual=matching_claim.value if matching_claim else None,
                required=fact.required,
                correct=correct,
                evidence=matching_claim.evidence if matching_claim else "",
            )
        )

    claims_correct = 0
    for claim in claims:
        candidates = facts_by_key.get(claim.key, [])
        if any(fact_matches(fact, claim.value) for fact in candidates):
            claims_correct += 1
        elif candidates:
            reasons.add(FailureReason.WRONG_FACT)
        else:
            reasons.add(FailureReason.UNSUPPORTED_CLAIM)
    if required_correct < required_total:
        reasons.add(FailureReason.MISSING_REQUIRED_FACT)
    return (
        assessments,
        required_correct,
        required_total,
        claims_correct,
        len(claims),
        reasons,
    )


def _replenishment_actual(
    expectation, observation: CaseObservation, after_sources: dict[str, Any]
) -> Decimal | None:
    if expectation.claim_key:
        claim = next(
            (
                item
                for item in observation.claims
                if item.key == expectation.claim_key
            ),
            None,
        )
        return decimal_value(claim.value) if claim else None
    actual = lookup_path(
        after_sources.get(expectation.selector or "", MISSING), expectation.path
    )
    return decimal_value(actual)


class BusinessEvaluator:
    def evaluate(
        self,
        expectation: BusinessExpectation | None,
        observation: CaseObservation,
        *,
        should_clarify: bool = False,
    ) -> tuple[BusinessEvaluation, set[FailureReason], dict[str, int]]:
        if expectation is None and not should_clarify:
            return BusinessEvaluation(), set(), {}
        expectation = expectation or BusinessExpectation()
        reasons: set[FailureReason] = set()
        before_sources = dict(observation.state_before)
        after_sources = {
            **observation.state_after,
            **observation.audit_records,
            **observation.operation_records,
        }

        feasibility_keys = {fact.key for fact in expectation.feasibility_facts}
        replenishment_key = (
            expectation.replenishment.claim_key
            if expectation.replenishment is not None
            else None
        )
        reserved_keys = feasibility_keys | ({replenishment_key} if replenishment_key else set())
        business_claims = [
            claim for claim in observation.claims if claim.key not in reserved_keys
        ]
        (
            fact_assessments,
            required_correct,
            required_total,
            claims_correct,
            claims_total,
            fact_reasons,
        ) = _assess_facts(expectation.facts, business_claims)
        reasons.update(fact_reasons)
        state_assessments = [
            assess_state(item, before_sources, after_sources)
            for item in expectation.state_assertions
        ]
        if any(item.required and not item.correct for item in state_assessments):
            reasons.add(FailureReason.TARGET_STATE_MISMATCH)

        feasibility_claims = [
            claim for claim in observation.claims if claim.key in feasibility_keys
        ]
        feasibility_assessments, feasibility_correct, feasibility_total, _, _, feasibility_reasons = (
            _assess_facts(expectation.feasibility_facts, feasibility_claims)
        )
        fact_assessments.extend(feasibility_assessments)
        reasons.update(feasibility_reasons)
        if feasibility_correct < feasibility_total:
            reasons.add(FailureReason.INFEASIBLE_RECOMMENDATION)

        replenishment_deviation: float | None = None
        replenishment_ok = True
        if expectation.replenishment is not None:
            actual = _replenishment_actual(
                expectation.replenishment, observation, after_sources
            )
            expected = Decimal(str(expectation.replenishment.expected_quantity))
            if actual is None:
                replenishment_ok = False
            else:
                denominator = abs(expected) if expected else Decimal("1")
                replenishment_deviation = float(abs(actual - expected) / denominator)
                replenishment_ok = (
                    replenishment_deviation
                    <= expectation.replenishment.tolerance_ratio
                )
            if not replenishment_ok:
                reasons.add(FailureReason.REPLENISHMENT_DEVIATION)

        if should_clarify:
            task_completed = observation.correct_clarification is True
            if not task_completed:
                reasons.add(FailureReason.MISSING_CLARIFICATION)
        else:
            task_completed = (
                required_correct == required_total
                and all(
                    not item.required or item.correct for item in state_assessments
                )
                and feasibility_correct == feasibility_total
                and replenishment_ok
                and not {FailureReason.WRONG_FACT, FailureReason.UNSUPPORTED_CLAIM}.intersection(reasons)
            )

        counts = {
            "required_correct": required_correct,
            "required_total": required_total,
            "claims_correct": claims_correct,
            "claims_total": claims_total,
        }
        return (
            BusinessEvaluation(
                applicable=True,
                task_completed=task_completed,
                fact_assessments=fact_assessments,
                state_assessments=state_assessments,
                feasibility_correct=feasibility_correct,
                feasibility_total=feasibility_total,
                replenishment_deviation=replenishment_deviation,
            ),
            reasons,
            counts,
        )
