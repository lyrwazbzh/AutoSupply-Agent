"""Typed contracts for the four-dimension full-agent evaluation.

The report intentionally has no weighted total score. Trajectory, business
quality, safety and stability remain independent so a strong result in one
dimension cannot hide a failure in another.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaseOutcome(str, Enum):
    FULLY_RESOLVED = "FULLY_RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    CORRECT_CLARIFICATION = "CORRECT_CLARIFICATION"
    INCORRECT = "INCORRECT"
    UNSAFE = "UNSAFE"
    INFRA_ERROR = "INFRA_ERROR"


class ResolutionKind(str, Enum):
    ANSWERED = "ANSWERED"
    NO_RESULT = "NO_RESULT"


class EvaluationSuite(str, Enum):
    TRAJECTORY = "trajectory"
    BUSINESS = "business"
    SAFETY = "safety"
    STABILITY = "stability"


class FailureReason(str, Enum):
    WRONG_FACT = "WRONG_FACT"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    WRONG_TOOL_FLOW = "WRONG_TOOL_FLOW"
    WRONG_TOOL_ARGUMENT = "WRONG_TOOL_ARGUMENT"
    WRONG_TOOL_ORDER = "WRONG_TOOL_ORDER"
    FALSE_SUCCESS_CLAIM = "FALSE_SUCCESS_CLAIM"
    MISSING_CLARIFICATION = "MISSING_CLARIFICATION"
    UNNECESSARY_CLARIFICATION = "UNNECESSARY_CLARIFICATION"
    MISSING_REQUIRED_FACT = "MISSING_REQUIRED_FACT"
    TARGET_STATE_MISMATCH = "TARGET_STATE_MISMATCH"
    INFEASIBLE_RECOMMENDATION = "INFEASIBLE_RECOMMENDATION"
    REPLENISHMENT_DEVIATION = "REPLENISHMENT_DEVIATION"
    RISK_NOT_INTERCEPTED = "RISK_NOT_INTERCEPTED"
    LEGAL_WRITE_FALSE_BLOCK = "LEGAL_WRITE_FALSE_BLOCK"


class FactOperator(str, Enum):
    EQ = "eq"
    CONTAINS = "contains"
    CONTAINS_SET = "contains_set"
    NUMERIC_CLOSE = "numeric_close"


class StateOperator(str, Enum):
    EQ = "eq"
    NOT_EQ = "not_eq"
    CONTAINS = "contains"
    CONTAINS_SET = "contains_set"
    NUMERIC_CLOSE = "numeric_close"
    EXISTS = "exists"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    DELTA = "delta"


class ExpectedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    value: Any
    required: bool = True
    operator: FactOperator = FactOperator.EQ
    tolerance: float = Field(default=0.0, ge=0.0)
    aliases: list[str] = Field(default_factory=list)


class ActualClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    value: Any
    text: str = ""
    evidence: str = ""


class ArgumentConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    value: Any
    operator: FactOperator = FactOperator.EQ
    tolerance: float = Field(default=0.0, ge=0.0)


class ToolActionExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1)
    tools: list[str] = Field(min_length=1)
    arguments: list[ArgumentConstraint] = Field(default_factory=list)
    min_calls: int = Field(default=1, ge=1)
    max_calls: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_call_bounds(self) -> "ToolActionExpectation":
        if self.max_calls is not None and self.max_calls < self.min_calls:
            raise ValueError("max_calls不能小于min_calls")
        return self


class OrderConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before: str = Field(min_length=1)
    after: str = Field(min_length=1)


class TrajectoryPath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_id: str = Field(min_length=1)
    actions: list[ToolActionExpectation] = Field(min_length=1)
    order: list[OrderConstraint] = Field(default_factory=list)


class TrajectoryContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_actions: list[ToolActionExpectation] = Field(default_factory=list)
    order: list[OrderConstraint] = Field(default_factory=list)
    alternative_paths: list[TrajectoryPath] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_phases: list[str] = Field(default_factory=list)
    phase_order: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_policy(self) -> "TrajectoryContract":
        if set(self.allowed_tools).intersection(self.forbidden_tools):
            raise ValueError("同一工具不能同时允许和禁止")
        action_ids = [item.action_id for item in self.required_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("required_actions包含重复action_id")
        return self


class StateAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    path: str = ""
    operator: StateOperator = StateOperator.EQ
    value: Any = None
    tolerance: float = Field(default=0.0, ge=0.0)
    required: bool = True


class ReplenishmentExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_quantity: float
    tolerance_ratio: float = Field(default=0.0, ge=0.0)
    claim_key: str | None = None
    selector: str | None = None
    path: str = ""

    @model_validator(mode="after")
    def validate_quantity_source(self) -> "ReplenishmentExpectation":
        if not self.claim_key and not self.selector:
            raise ValueError("补货评测必须声明claim_key或selector")
        return self


class BusinessExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: Literal[
        "generic", "query", "write", "recommendation", "replenishment"
    ] = "generic"
    facts: list[ExpectedFact] = Field(default_factory=list)
    state_assertions: list[StateAssertion] = Field(default_factory=list)
    feasibility_facts: list[ExpectedFact] = Field(default_factory=list)
    replenishment: ReplenishmentExpectation | None = None


class SafetyExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_block: bool = False
    legitimate_write: bool = False
    attack_type: str = "unauthorized_mutation"
    protected_state: list[StateAssertion] = Field(default_factory=list)
    forbidden_claim_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_safety_mode(self) -> "SafetyExpectation":
        if self.should_block and self.legitimate_write:
            raise ValueError("安全用例不能同时要求拦截并声明为合法写入")
        return self


class StabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trials: int = Field(default=3, ge=3)
    input_variants: list[str] = Field(default_factory=list)
    fault_profiles: list[str] = Field(default_factory=list)


class EvidenceProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    path: str = Field(min_length=1)
    method: Literal["GET", "POST"] = "GET"
    phase: Literal["before", "after", "both"] = "both"
    target: Literal["state", "audit", "operation"] = "state"
    params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)


class EvaluationEnvironmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requires_reset: bool = False
    reset_payload: dict[str, Any] = Field(default_factory=dict)
    probes: list[EvidenceProbe] = Field(default_factory=list)


class EvaluationExpectation(BaseModel):
    """Unified expectation with compatibility fields for the existing dataset."""

    model_config = ConfigDict(extra="forbid")

    facts: list[ExpectedFact] = Field(default_factory=list)
    should_clarify: bool = False
    clarification_markers: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    legal_write: bool = False
    resolution_kind: ResolutionKind = ResolutionKind.ANSWERED
    trajectory: TrajectoryContract | None = None
    business: BusinessExpectation | None = None
    safety: SafetyExpectation | None = None
    stability: StabilityConfig | None = None

    @model_validator(mode="after")
    def normalize_legacy_contract(self) -> "EvaluationExpectation":
        if self.should_clarify and (self.facts or (self.business and self.business.facts)):
            raise ValueError("澄清用例不能同时声明必须直接回答的业务事实")
        if set(self.required_tools).intersection(self.forbidden_tools):
            raise ValueError("同一工具不能同时为required_tools和forbidden_tools")
        if self.allowed_tools and not set(self.required_tools).issubset(
            self.allowed_tools
        ):
            raise ValueError("required_tools必须包含在allowed_tools中")
        if self.legal_write and not (self.required_tools or self.trajectory):
            raise ValueError("legal_write用例必须声明工具轨迹")

        if self.trajectory is None and (
            self.required_tools or self.allowed_tools or self.forbidden_tools
        ):
            self.trajectory = TrajectoryContract(
                required_actions=[
                    ToolActionExpectation(action_id=name, tools=[name])
                    for name in self.required_tools
                ],
                allowed_tools=self.allowed_tools,
                forbidden_tools=self.forbidden_tools,
            )
        if self.business is None and self.facts:
            self.business = BusinessExpectation(facts=self.facts)
        if self.safety is None and (self.forbidden_tools or self.legal_write):
            self.safety = SafetyExpectation(
                should_block=bool(self.forbidden_tools),
                legitimate_write=self.legal_write,
            )
        return self


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    thread_id: str | None = None
    user_id: str = "evaluation-user"
    username: str = "评测用户"


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    split: Literal["example", "development", "calibration", "hidden"]
    domain: str = Field(min_length=1)
    difficulty: Literal["L1", "L2", "L3", "L4"]
    request: EvaluationRequest
    expected: EvaluationExpectation
    suites: list[EvaluationSuite] = Field(default_factory=list)
    environment: EvaluationEnvironmentSpec = Field(
        default_factory=EvaluationEnvironmentSpec
    )
    resume_decisions: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    def enabled_suites(self) -> set[EvaluationSuite]:
        if self.suites:
            return set(self.suites)
        enabled: set[EvaluationSuite] = set()
        if self.expected.trajectory is not None:
            enabled.add(EvaluationSuite.TRAJECTORY)
        if self.expected.business is not None or self.expected.should_clarify:
            enabled.add(EvaluationSuite.BUSINESS)
        if self.expected.safety is not None:
            enabled.add(EvaluationSuite.SAFETY)
        if self.expected.stability is not None:
            enabled.add(EvaluationSuite.STABILITY)
        return enabled


class ToolCallObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = ""
    sequence: int = 0
    name: str = Field(min_length=1)
    arguments: Any = None
    result: Any = None
    status: Literal["success", "error", "interrupted"] = "success"
    error_source: Literal["agent", "business", "infra", "none"] = "none"
    side_effect_applied: bool = False
    operation_id: str | None = None

    @property
    def counts_as_agent_error(self) -> bool:
        return self.status == "error" and self.error_source == "agent"


class SafetyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "unauthorized_mutation",
        "approval_bypass",
        "tampered_payload_mutation",
        "duplicate_write",
        "unknown_auto_replay",
        "cross_user_data_leakage",
        "missing_audit_record",
    ]
    detail: str = ""


class CaseObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = ""
    trial_index: int = Field(default=1, ge=1)
    final_answer: str = ""
    claims: list[ActualClaim] = Field(default_factory=list)
    tool_calls: list[ToolCallObservation] = Field(default_factory=list)
    asked_clarification: bool = False
    correct_clarification: bool | None = None
    safety_events: list[SafetyEvent] = Field(default_factory=list)
    infra_error: str | None = None
    raw_events: list[dict[str, Any]] = Field(default_factory=list)
    harness_trace: list[dict[str, Any]] = Field(default_factory=list)
    state_before: dict[str, Any] = Field(default_factory=dict)
    state_after: dict[str, Any] = Field(default_factory=dict)
    audit_records: dict[str, Any] = Field(default_factory=dict)
    operation_records: dict[str, Any] = Field(default_factory=dict)
    fault_profile: str | None = None
    fault_injected: bool = False
    fault_recovered: bool | None = None


class CaseCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_correct: int = 0
    required_total: int = 0
    claims_correct: int = 0
    claims_total: int = 0
    tool_errors: int = 0
    tool_calls: int = 0
    trajectory_correct: int = 0
    trajectory_total: int = 0
    clarification_expected: int = 0
    clarification_correct: int = 0


class FactAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    expected: Any = None
    actual: Any = None
    required: bool = True
    correct: bool = False
    evidence: str = ""


class StateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    selector: str
    path: str = ""
    operator: StateOperator
    expected: Any = None
    required: bool = True
    before: Any = None
    after: Any = None
    correct: bool = False


class TrajectoryEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable: bool = False
    passed: bool | None = None
    accurate_calls: int = 0
    total_calls: int = 0
    matched_path: str | None = None
    diagnostics: list[str] = Field(default_factory=list)


class BusinessEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable: bool = False
    task_completed: bool | None = None
    fact_assessments: list[FactAssessment] = Field(default_factory=list)
    state_assessments: list[StateAssessment] = Field(default_factory=list)
    feasibility_correct: int = 0
    feasibility_total: int = 0
    replenishment_deviation: float | None = None


class SafetyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable: bool = False
    expected_risk: bool = False
    risk_intercepted: bool | None = None
    legitimate_write: bool = False
    false_blocked: bool | None = None
    protected_state_assessments: list[StateAssessment] = Field(
        default_factory=list
    )


class TrialStabilityEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fault_profile: str | None = None
    fault_injected: bool = False
    fault_recovered: bool | None = None


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    thread_id: str = ""
    trial_index: int = 1
    domain: str
    difficulty: str
    outcome: CaseOutcome
    resolution_kind: ResolutionKind | None = None
    failure_reasons: list[FailureReason] = Field(default_factory=list)
    counts: CaseCounts = Field(default_factory=CaseCounts)
    fact_assessments: list[FactAssessment] = Field(default_factory=list)
    safety_events: list[SafetyEvent] = Field(default_factory=list)
    trajectory: TrajectoryEvaluation = Field(default_factory=TrajectoryEvaluation)
    business: BusinessEvaluation = Field(default_factory=BusinessEvaluation)
    safety_evaluation: SafetyEvaluation = Field(default_factory=SafetyEvaluation)
    stability: TrialStabilityEvaluation = Field(
        default_factory=TrialStabilityEvaluation
    )
    infra_error: str | None = None
    final_answer: str = ""
    tool_calls: list[ToolCallObservation] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome in {
            CaseOutcome.FULLY_RESOLVED,
            CaseOutcome.CORRECT_CLARIFICATION,
        }


class TrajectoryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trajectory_pass_rate: float | None = None
    tool_call_accuracy: float | None = None


class BusinessMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_completion_rate: float | None = None
    key_fact_accuracy: float | None = None
    recommendation_feasibility_rate: float | None = None
    replenishment_quantity_deviation: float | None = None


class SafetyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_operation_interception_rate: float | None = None
    legitimate_write_false_block_rate: float | None = None


class StabilityMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pass_3: float | None = None
    fault_recovery_rate: float | None = None


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trajectory: TrajectoryMetrics = Field(default_factory=TrajectoryMetrics)
    business: BusinessMetrics = Field(default_factory=BusinessMetrics)
    safety: SafetyMetrics = Field(default_factory=SafetyMetrics)
    stability: StabilityMetrics = Field(default_factory=StabilityMetrics)


class ReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: Literal["full_agent_four_dimension_evaluation"] = (
        "full_agent_four_dimension_evaluation"
    )
    schema_version: Literal["2.0"] = "2.0"
    dataset_version: str
    git_commit: str = "unknown"
    model: str = "unknown"
    prompt_version: str = "unknown"
    erp_version: str = "unknown"
    fixture_version: str = "unknown"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: ReportMetadata
    status: Literal["COMPLETE", "INCOMPLETE"]
    metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)
    outcomes: dict[str, float]
    domains: dict[str, dict[str, Any]]
    safety_events: dict[str, int]
    failure_reasons: dict[str, int]
    cases: list[EvaluationResult]
