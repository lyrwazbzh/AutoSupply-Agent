"""评测指标聚合与 JSON 报告读写。

展示层由外部 Java 前端负责；本模块只提供评测结果的稳定数据结构。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

SRC_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = SRC_ROOT / "test" / "evaluation" / "last_evaluation_report.json"
REPORT_PATH = Path(os.getenv("EVALUATION_REPORT_PATH", str(DEFAULT_REPORT_PATH)))


@dataclass
class CaseMetric:
    case: str
    category: str
    ok: bool
    detail: str = ""
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MetricsBoard:
    """聚合评测用例结果，不负责 HTML 渲染。"""

    rows: list[CaseMetric] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def add(
        self,
        case: str,
        ok: bool,
        *,
        category: str = "task_success",
        detail: str = "",
        ms: float = 0.0,
    ) -> None:
        self.rows.append(
            CaseMetric(case=case, category=category, ok=ok, detail=detail, ms=round(ms, 1))
        )

    def summary(self) -> dict[str, Any]:
        total = len(self.rows)
        passed = sum(1 for row in self.rows if row.ok)
        by_category: dict[str, dict[str, Any]] = {}
        for row in self.rows:
            bucket = by_category.setdefault(
                row.category, {"total": 0, "passed": 0, "latencies_ms": []}
            )
            bucket["total"] += 1
            if row.ok:
                bucket["passed"] += 1
            if row.ms:
                bucket["latencies_ms"].append(row.ms)

        categories: dict[str, Any] = {}
        for category, bucket in by_category.items():
            latencies = bucket["latencies_ms"]
            categories[category] = {
                "total": bucket["total"],
                "passed": bucket["passed"],
                "pass_rate": round(bucket["passed"] / bucket["total"], 4)
                if bucket["total"]
                else 0,
                "p50_ms": round(sorted(latencies)[len(latencies) // 2], 1)
                if latencies
                else 0,
                "avg_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
            }

        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_ms": round((time.time() - self.started_at) * 1000, 1),
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4) if total else 0,
            "categories": categories,
            "kpis": {
                "task_success_rate": categories.get("task_success", {}).get("pass_rate")
                or categories.get("clarify", {}).get("pass_rate")
                or (round(passed / total, 4) if total else 0),
                "numeric_accuracy": categories.get("numeric_accuracy", {}).get("pass_rate", 0),
                "write_safety": categories.get("write_safety", {}).get("pass_rate", 0),
                "rag_citation": categories.get("rag", {}).get("pass_rate", 0),
                "avg_latency_ms": round(
                    sum(row.ms for row in self.rows if row.ms)
                    / max(1, sum(1 for row in self.rows if row.ms)),
                    1,
                ),
            },
            "cases": [row.to_dict() for row in self.rows],
        }

    def dump(self, path: Optional[Path] = None) -> Path:
        target = path or REPORT_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.summary(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return target


def load_latest(path: Optional[Path] = None) -> dict[str, Any]:
    target = path or REPORT_PATH
    if not target.exists():
        return MetricsBoard().summary()
    return json.loads(target.read_text(encoding="utf-8"))
