from __future__ import annotations

import asyncio
import json

import pytest

from src.evaluation.claims import LLMClaimExtractor
from src.evaluation.models import (
    EvaluationCase,
    EvaluationMetrics,
    EvaluationReport,
    ReportMetadata,
    ToolCallObservation,
)
from src.evaluation.report_store import dump_report, load_report
from src.evaluation.runner import (
    AgentSseClient,
    load_jsonl,
    observation_from_events,
    parse_sse,
)


def _case(**expected) -> EvaluationCase:
    return EvaluationCase.model_validate(
        {
            "case_id": "SSE-001",
            "dataset_version": "test-v1",
            "split": "development",
            "domain": "inventory",
            "difficulty": "L2",
            "request": {"message": "查询库存"},
            "expected": expected,
        }
    )


def test_parse_sse_and_build_observation_from_real_protocol_shape():
    lines = [
        "event: tool_start",
        'data: {"id":"call-1","name":"inventory_query"}',
        "",
        "event: tool_args",
        'data: {"args":"{\\\"partId\\\":1}"}',
        "",
        "event: tool_result",
        'data: {"name":"inventory_query","content":"{\\\"code\\\":200,\\\"data\\\":{\\\"quantity\\\":12}}"}',
        "",
        "event: token",
        'data: {"source":"main","content":"当前库存为12件。"}',
        "",
        "event: done",
        "data: {}",
        "",
    ]
    events = parse_sse(lines)
    observation = observation_from_events(
        events,
        _case(required_tools=["inventory_query"], allowed_tools=["inventory_query"]),
    )

    assert observation.final_answer == "当前库存为12件。"
    assert len(observation.tool_calls) == 1
    assert observation.tool_calls[0].name == "inventory_query"
    assert observation.tool_calls[0].status == "success"
    assert observation.tool_calls[0].error_source == "none"
    assert not observation.tool_calls[0].side_effect_applied


def test_agent_parameter_error_is_counted_but_business_rejection_is_not():
    case = _case()
    events = parse_sse(
        [
            "event: tool_result",
            'data: {"name":"part_query","content":"{\\\"code\\\":400}"}',
            "",
            "event: tool_result",
            'data: {"name":"order_create","content":"{\\\"code\\\":409}"}',
            "",
            "event: done",
            "data: {}",
            "",
        ]
    )
    observation = observation_from_events(events, case)

    assert observation.tool_calls[0].error_source == "agent"
    assert observation.tool_calls[1].error_source == "business"


def test_missing_sse_terminal_event_is_infrastructure_error():
    observation = observation_from_events(
        parse_sse(
            [
                "event: token",
                'data: {"source":"main","content":"半截回答"}',
                "",
            ]
        ),
        _case(),
    )
    assert "终态事件" in observation.infra_error


def test_claim_extractor_never_receives_gold_values_or_tool_results():
    class FakeStructuredModel:
        prompt = ""

        async def ainvoke(self, prompt):
            self.prompt = prompt
            return {"claims": []}

    class FakeModel:
        def __init__(self):
            self.structured = FakeStructuredModel()

        def with_structured_output(self, _schema):
            return self.structured

    model = FakeModel()
    extractor = LLMClaimExtractor(model)
    case = _case(facts=[{"key": "inventory.quantity", "value": 987654321}])
    asyncio.run(
        extractor.extract(
            case,
            "库存数量未知",
            [
                ToolCallObservation(
                    name="inventory_query",
                    result={"secret_result": 246813579},
                )
            ],
        )
    )

    assert "inventory.quantity" in model.structured.prompt
    assert "987654321" not in model.structured.prompt
    assert "246813579" not in model.structured.prompt


def test_jsonl_loader_validates_rows_and_duplicate_ids(tmp_path):
    valid = _case().model_dump_json()
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(valid + "\n", encoding="utf-8")
    assert load_jsonl(dataset)[0].case_id == "SSE-001"

    dataset.write_text(valid + "\n" + valid + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="重复case_id"):
        load_jsonl(dataset)


def test_report_store_accepts_only_current_schema(tmp_path):
    path = tmp_path / "report.json"
    expected = EvaluationReport(
        metadata=ReportMetadata(dataset_version="test-v1"),
        status="COMPLETE",
        metrics=EvaluationMetrics(),
        outcomes={},
        domains={},
        safety_events={},
        failure_reasons={},
        cases=[],
    )
    dump_report(expected, path)
    assert load_report(path) == expected.model_dump(mode="json")

    path.write_text(json.dumps({"status": "COMPLETE"}), encoding="utf-8")
    with pytest.raises(ValueError, match="无效的完整Agent评测报告"):
        load_report(path)


def test_write_evaluation_uses_independent_checker_before_applicant_resume():
    class FakeClient(AgentSseClient):
        def __init__(self):
            super().__init__("http://agent", approval_headers={"Authorization": "Bearer checker"})
            self.stream_calls = []
            self.approvals = []

        async def _post_stream(self, path, payload):
            self.stream_calls.append((path, payload))
            if path == "/api/chat/stream":
                return [
                    {"event": "interrupt", "data": {"operation_ids": ["op-eval-1"]}},
                    {"event": "done", "data": {"interrupted": True}},
                ]
            return [
                {"event": "token", "data": {"content": "已执行", "source": "main"}},
                {"event": "done", "data": {"interrupted": False}},
            ]

        async def _post_approval(self, operation_id, decision):
            self.approvals.append((operation_id, decision))

    case = EvaluationCase.model_validate(
        {
            "case_id": "WRITE-001",
            "dataset_version": "test-v1",
            "split": "development",
            "domain": "inventory_write",
            "difficulty": "L3",
            "request": {"message": "入库"},
            "expected": {
                "required_tools": ["inventory_inbound"],
                "allowed_tools": ["inventory_inbound"],
                "legal_write": True,
            },
            "resume_decisions": [{"type": "approve"}],
        }
    )
    client = FakeClient()
    observation = asyncio.run(client.run(case))

    assert observation.infra_error is None
    assert client.approvals == [("op-eval-1", {"type": "approve"})]
    assert client.stream_calls[-1][1] == {"resume": {"check_approval": True}}
