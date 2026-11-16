"""采购上下文压缩策略回归测试。"""

from __future__ import annotations

import importlib.metadata
import unittest

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.context_compaction import (
    ContextCompactionSettings,
    build_procurement_summary_prompt,
    create_context_compaction_middleware,
)
from src.agent.middleware_config import get_all_subagent_middlewares


class ToolCapableFakeModel(FakeMessagesListChatModel):
    """DeepAgents 总会绑定内置工具，测试模型只需接受绑定即可。"""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


class TestContextCompactionSettings(unittest.TestCase):
    def test_default_window_math(self):
        settings = ContextCompactionSettings()

        settings.validate()

        self.assertEqual(settings.context_window_tokens, 128_000)
        self.assertEqual(settings.trigger_tokens, 96_000)
        self.assertEqual(settings.keep_tokens, 19_200)
        self.assertEqual(settings.schema_version, "procurement-v1")

    def test_invalid_ratios_fail_closed(self):
        invalid = (
            ContextCompactionSettings(trigger_ratio=0.0),
            ContextCompactionSettings(keep_ratio=0.0),
            ContextCompactionSettings(trigger_ratio=1.0),
            ContextCompactionSettings(trigger_ratio=0.5, keep_ratio=0.5),
            ContextCompactionSettings(context_window_tokens=0),
            ContextCompactionSettings(schema_version=""),
        )

        for settings in invalid:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                settings.validate()

    def test_deepagents_patch_version_is_pinned(self):
        self.assertEqual(importlib.metadata.version("deepagents"), "0.7.35")


class TestProcurementSummaryContract(unittest.TestCase):
    def test_prompt_preserves_framework_markers_and_business_fields(self):
        prompt = build_procurement_summary_prompt("procurement-test-v1")

        self.assertEqual(prompt.count("{messages}"), 1)
        self.assertEqual(prompt.count("<messages>"), 1)
        self.assertIn("procurement-test-v1", prompt)
        for required in (
            "partId",
            "partCode",
            "supplierId",
            "supplierCode",
            "orderId",
            "orderNo",
            "operationId",
            "idempotencyKey",
            "APPROVAL STATE",
            "OPEN WORK AND CLARIFICATIONS",
        ):
            self.assertIn(required, prompt)

        self.assertIn("requested write must never be described as completed", prompt)
        self.assertIn("Never turn a failed tool call into success", prompt)
        self.assertIn("source of truth for any future write", prompt)


class TestContextCompactionMiddleware(unittest.TestCase):
    @staticmethod
    def _model(*responses: str) -> ToolCapableFakeModel:
        return ToolCapableFakeModel(
            responses=[AIMessage(content=response) for response in responses]
        )

    def test_explicit_absolute_thresholds_replace_profile_guessing(self):
        middleware = create_context_compaction_middleware(
            model=self._model("unused"),
            backend=StateBackend(),
            settings=ContextCompactionSettings(
                context_window_tokens=10_000,
                trigger_ratio=0.7,
                keep_ratio=0.2,
                schema_version="test-v1",
            ),
        )

        self.assertEqual(middleware.name, "SummarizationMiddleware")
        self.assertEqual(middleware._lc_helper.trigger, ("tokens", 7_000))
        self.assertEqual(middleware._lc_helper.keep, ("tokens", 2_000))
        self.assertIsNone(middleware._lc_helper.trim_tokens_to_summarize)

    def test_main_style_compaction_offloads_full_history(self):
        model = self._model(
            "summary keeps PO202611120001 and operationId=op-123",
            "done",
        )
        backend = StateBackend()
        middleware = create_context_compaction_middleware(
            model=model,
            backend=backend,
            settings=ContextCompactionSettings(
                context_window_tokens=1_000,
                trigger_ratio=0.5,
                keep_ratio=0.2,
                schema_version="test-v1",
            ),
        )
        agent = create_deep_agent(
            model=model,
            backend=backend,
            middleware=[middleware],
        )
        old_fact = (
            "partCode=PART-SP-001 supplierCode=SUP-002 "
            "orderNo=PO202611120001 operationId=op-123 "
            "idempotencyKey=idem-456 status=PENDING_APPROVAL "
        )

        result = agent.invoke(
            {
                "messages": [
                    HumanMessage(content=old_fact + "x" * 3_000),
                    HumanMessage(content="最近一条消息必须原样保留"),
                ]
            }
        )

        history_files = {
            path: payload
            for path, payload in result["files"].items()
            if path.startswith("/conversation_history/")
        }
        self.assertEqual(len(history_files), 1)
        history = next(iter(history_files.values()))["content"]
        for exact_value in (
            "PART-SP-001",
            "SUP-002",
            "PO202611120001",
            "op-123",
            "idem-456",
            "PENDING_APPROVAL",
        ):
            self.assertIn(exact_value, history)
        self.assertEqual(result["messages"][-1].content, "done")
        self.assertEqual(result["messages"][-2].content, "最近一条消息必须原样保留")

    def test_subagents_receive_independent_matching_policy(self):
        model = self._model("unused")
        backend = StateBackend()

        by_agent = get_all_subagent_middlewares(
            sandbox_backend=object(),
            model=model,
            compaction_backend=backend,
        )

        analyst = by_agent["procurement-analyst"][0]
        order = by_agent["procurement-order"][0]
        self.assertEqual(analyst.name, "SummarizationMiddleware")
        self.assertEqual(order.name, "SummarizationMiddleware")
        self.assertIsNot(analyst, order)
        self.assertEqual(analyst._lc_helper.trigger, order._lc_helper.trigger)
        self.assertEqual(analyst._lc_helper.keep, order._lc_helper.keep)


if __name__ == "__main__":
    unittest.main()
