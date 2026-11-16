"""Deterministic value and evidence matching shared by all evaluators."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import (
    ArgumentConstraint,
    ExpectedFact,
    FactOperator,
    StateAssertion,
    StateAssessment,
    StateOperator,
)

MISSING = object()


def normalized(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.strip().casefold().split())
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalized(item) for key, item in value.items()}
    return value


def decimal_value(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def matches_value(
    expected: Any,
    actual: Any,
    operator: FactOperator,
    tolerance: float = 0.0,
) -> bool:
    if actual is MISSING:
        return False
    if operator == FactOperator.NUMERIC_CLOSE:
        left = decimal_value(expected)
        right = decimal_value(actual)
        return bool(
            left is not None
            and right is not None
            and abs(left - right) <= Decimal(str(tolerance))
        )

    expected_value = normalized(expected)
    actual_value = normalized(actual)
    if operator == FactOperator.EQ:
        return actual_value == expected_value
    if operator == FactOperator.CONTAINS:
        if isinstance(actual_value, str):
            return str(expected_value) in actual_value
        if isinstance(actual_value, list):
            return expected_value in actual_value
        return False
    if operator == FactOperator.CONTAINS_SET:
        if not isinstance(expected_value, list) or not isinstance(actual_value, list):
            return False
        return set(map(str, expected_value)).issubset(set(map(str, actual_value)))
    return False


def fact_matches(expected: ExpectedFact, actual: Any) -> bool:
    return matches_value(
        expected.value, actual, expected.operator, expected.tolerance
    )


def parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


_PATH_TOKEN = re.compile(r"([^.[\]]+)|\[(\d+)\]")


def lookup_path(value: Any, path: str) -> Any:
    if not path:
        return value
    current = value
    for name, index in _PATH_TOKEN.findall(path):
        if name:
            if not isinstance(current, dict) or name not in current:
                return MISSING
            current = current[name]
        else:
            position = int(index)
            if not isinstance(current, list) or position >= len(current):
                return MISSING
            current = current[position]
    return current


def argument_matches(constraint: ArgumentConstraint, arguments: Any) -> bool:
    actual = lookup_path(parse_json_value(arguments), constraint.path)
    return matches_value(
        constraint.value, actual, constraint.operator, constraint.tolerance
    )


def assess_state(
    assertion: StateAssertion,
    before_sources: dict[str, Any],
    after_sources: dict[str, Any],
) -> StateAssessment:
    before = lookup_path(before_sources.get(assertion.selector, MISSING), assertion.path)
    after = lookup_path(after_sources.get(assertion.selector, MISSING), assertion.path)
    operator = assertion.operator

    if operator == StateOperator.EXISTS:
        correct = after is not MISSING
    elif operator == StateOperator.CHANGED:
        correct = before is not MISSING and after is not MISSING and before != after
    elif operator == StateOperator.UNCHANGED:
        correct = before is not MISSING and after is not MISSING and before == after
    elif operator == StateOperator.DELTA:
        before_number = decimal_value(before)
        after_number = decimal_value(after)
        expected_number = decimal_value(assertion.value)
        correct = bool(
            before_number is not None
            and after_number is not None
            and expected_number is not None
            and abs((after_number - before_number) - expected_number)
            <= Decimal(str(assertion.tolerance))
        )
    else:
        fact_operator = {
            StateOperator.EQ: FactOperator.EQ,
            StateOperator.NOT_EQ: FactOperator.EQ,
            StateOperator.CONTAINS: FactOperator.CONTAINS,
            StateOperator.CONTAINS_SET: FactOperator.CONTAINS_SET,
            StateOperator.NUMERIC_CLOSE: FactOperator.NUMERIC_CLOSE,
        }[operator]
        correct = matches_value(
            assertion.value, after, fact_operator, assertion.tolerance
        )
        if operator == StateOperator.NOT_EQ:
            correct = after is not MISSING and not correct

    return StateAssessment(
        key=assertion.key,
        selector=assertion.selector,
        path=assertion.path,
        operator=assertion.operator,
        expected=assertion.value,
        required=assertion.required,
        before=None if before is MISSING else before,
        after=None if after is MISSING else after,
        correct=correct,
    )
