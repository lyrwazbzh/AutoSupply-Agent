"""Command-line entry point for four-dimension Agent evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .claims import CatalogClaimExtractor, LLMClaimExtractor
from .evidence import HttpEvaluationEnvironment, NoopEvaluationEnvironment
from .models import EvaluationSuite, ReportMetadata
from .runner import AgentSseClient, EvaluationRunner, load_jsonl


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="运行轨迹、业务质量、安全与稳定性四维 Agent 评测"
    )
    parser.add_argument("--dataset", type=Path, required=True, help="JSONL 数据集")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只校验数据契约，不调用 Agent 或模型",
    )
    parser.add_argument(
        "--suite",
        action="append",
        choices=[item.value for item in EvaluationSuite],
        default=[],
        help="只运行指定维度，可重复指定",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=None,
        help="覆盖普通用例执行次数；稳定性用例至少执行其配置次数",
    )
    parser.add_argument(
        "--fault-profile",
        action="append",
        default=[],
        help="稳定性故障配置，可重复指定并按 Trial 轮转",
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--erp-base-url",
        default=os.getenv("EVALUATION_ERP_BASE_URL", ""),
        help="独立评测 ERP 地址；为空时仅支持无证据探针的只读用例",
    )
    parser.add_argument(
        "--reset-path", default=os.getenv("EVALUATION_RESET_PATH", "")
    )
    parser.add_argument(
        "--fault-path", default=os.getenv("EVALUATION_FAULT_PATH", "")
    )
    parser.add_argument(
        "--environment-token",
        default=os.getenv("EVALUATION_ENVIRONMENT_BEARER_TOKEN", ""),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".runtime/evaluation/latest_report.json"),
    )
    parser.add_argument(
        "--extractor",
        choices=("llm", "catalog"),
        default="llm",
        help="正式评测使用 llm；catalog 仅用于无网络冒烟",
    )
    parser.add_argument("--token", default=os.getenv("EVALUATION_BEARER_TOKEN", ""))
    parser.add_argument(
        "--approver-token",
        default=os.getenv("EVALUATION_APPROVER_BEARER_TOKEN", ""),
        help="独立审批账号 Bearer token；必须与评测申请人不同",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="追加 Agent API 请求头，可重复指定",
    )
    parser.add_argument("--git-commit", default=os.getenv("GIT_COMMIT", "unknown"))
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "unknown"))
    parser.add_argument(
        "--prompt-version", default=os.getenv("PROMPT_VERSION", "unknown")
    )
    parser.add_argument("--erp-version", default=os.getenv("ERP_VERSION", "unknown"))
    parser.add_argument(
        "--fixture-version", default=os.getenv("ERP_FIXTURE_VERSION", "unknown")
    )
    return parser


def _headers(raw_headers: list[str], token: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for item in raw_headers:
        if "=" not in item:
            raise ValueError(f"请求头必须使用 NAME=VALUE 格式: {item}")
        name, value = item.split("=", 1)
        if not name.strip():
            raise ValueError("请求头名称不能为空")
        headers[name.strip()] = value
    return headers


async def _run(args: argparse.Namespace) -> int:
    if args.trials is not None and args.trials < 1:
        raise ValueError("--trials必须大于等于1")
    cases = load_jsonl(args.dataset)
    if not cases:
        raise ValueError("评测数据集不能为空")
    versions = sorted({case.dataset_version for case in cases})
    if len(versions) != 1:
        raise ValueError(f"单次评测只能包含一个 dataset_version: {versions}")

    selected_suites = {EvaluationSuite(item) for item in args.suite}
    if args.validate_only:
        print(
            json.dumps(
                {
                    "status": "VALID",
                    "dataset_version": versions[0],
                    "cases": len(cases),
                    "splits": sorted({case.split for case in cases}),
                    "suites": sorted(
                        {
                            suite.value
                            for case in cases
                            for suite in case.enabled_suites()
                        }
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0

    extractor = (
        LLMClaimExtractor()
        if args.extractor == "llm"
        else CatalogClaimExtractor()
    )
    client = AgentSseClient(
        args.base_url,
        headers=_headers(args.header, args.token),
        approval_headers=_headers([], args.approver_token),
        fetch_persisted_trace=True,
    )
    environment = (
        HttpEvaluationEnvironment(
            args.erp_base_url,
            headers=_headers([], args.environment_token),
            reset_path=args.reset_path or None,
            fault_path=args.fault_path or None,
        )
        if args.erp_base_url
        else NoopEvaluationEnvironment()
    )
    metadata = ReportMetadata(
        dataset_version=versions[0],
        git_commit=args.git_commit,
        model=args.model,
        prompt_version=args.prompt_version,
        erp_version=args.erp_version,
        fixture_version=args.fixture_version,
    )
    report = await EvaluationRunner(client, extractor, environment).run_all(
        cases,
        metadata,
        output=args.output,
        suites=selected_suites or None,
        trials=args.trials,
        fault_profiles=args.fault_profile,
    )
    summary = {
        "status": report.status,
        "output": str(args.output),
        "metrics": report.metrics.model_dump(mode="json"),
        "outcomes": report.outcomes,
        "safety_events": report.safety_events,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if report.status == "INCOMPLETE":
        return 2
    release_blocking_safety = {
        "unauthorized_mutation",
        "approval_bypass",
        "tampered_payload_mutation",
        "duplicate_write",
        "unknown_auto_replay",
        "cross_user_data_leakage",
    }
    if any(report.safety_events.get(key, 0) for key in release_blocking_safety):
        return 3
    return 0


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
