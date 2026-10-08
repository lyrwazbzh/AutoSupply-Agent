"""Harness 审查开关 / 类型选型（不依赖 Docker、langchain、deepagents）。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

import yaml

from src.agent.harness_review import detect_task_type, review_text, should_use_grader


def _load_config() -> dict:
    path = Path(__file__).resolve().parents[1] / "agent" / "harness_config.yaml"
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class HumanMessage:
    type = "human"

    def __init__(self, content: str):
        self.content = content


class _ReviewEmbedder:
    _need = [1.0, 0.0]
    _skip = [0.0, 1.0]

    def embed_texts(self, texts):
        out = []
        for text in texts:
            blob = text or ""
            if any(token in blob for token in ("谢谢", "你好", "是什么意思")):
                out.append(list(self._skip))
            else:
                out.append(list(self._need))
        return out


_RESULTS: List = []


def test(func):
    _RESULTS.append(func)
    return func


@test
def test_trivial_skip():
    config = _load_config()
    for text in ("你好", "谢谢", "ERP是什么？", "库存是什么？"):
        assert should_use_grader([HumanMessage(text)], config) is False, text


@test
def test_compound_definition_grades():
    config = _load_config()
    assert should_use_grader(
        [HumanMessage("什么是 MRP，并列出本周缺料")], config
    )


@test
def test_sku_grades():
    config = _load_config()
    assert should_use_grader([HumanMessage("查 SKU-001 库存")], config)


@test
def test_follow_up_rewrite():
    config = _load_config()
    messages = [
        HumanMessage("对比了恒力机械的交期"),
        HumanMessage("那家还要多久到"),
    ]
    assert "恒力" in review_text(messages)
    assert should_use_grader(messages, config, _ReviewEmbedder())


@test
def test_keyword_tie_default_type():
    config = _load_config()
    messages = [HumanMessage("分析一下供应商")]
    assert detect_task_type(messages, config) == "default"


@test
def test_oral_grades_with_embedder():
    config = _load_config()
    assert should_use_grader(
        [HumanMessage("这票货还要多久到")], config, _ReviewEmbedder()
    )


@test
def test_inventory_keywords_still_grade():
    config = _load_config()
    assert should_use_grader(
        [HumanMessage("查询库存并给出低于安全库存的补货建议")], config
    )
    assert detect_task_type(
        [HumanMessage("查询库存并给出低于安全库存的补货建议")], config
    ) == "inventory"


def main() -> int:
    failed = 0
    for func in _RESULTS:
        try:
            func()
            print(f"  PASS  {func.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {func.__name__}")
            traceback.print_exc()
    print(f"\n{len(_RESULTS) - failed}/{len(_RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
