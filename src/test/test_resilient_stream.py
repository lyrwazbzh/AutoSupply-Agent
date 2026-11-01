import asyncio
import unittest
from unittest.mock import patch

from src.api_view.api import chat


class ResilientStreamTests(unittest.IsolatedAsyncioTestCase):
    def test_order_interrupt_is_serialized_for_history_restore(self):
        payload = chat._format_interrupt_data({
            "type": "order_info_request",
            "missing_fields": ["orderDetail[0].partId"],
            "current_data": {"orderDetail": [{"partId": None}]},
            "message": "请补充订单信息",
        })

        self.assertEqual(payload["interrupt_type"], "order_info_supplement")
        self.assertEqual(payload["missing_fields"], ["orderDetail[0].partId"])
        self.assertEqual(payload["extracted_data"]["orderDetail"][0]["partId"], None)

    async def test_agent_producer_survives_client_disconnect(self):
        allow_producer_to_finish = asyncio.Event()
        producer_finished = asyncio.Event()

        async def fake_stream_chat_response(**_kwargs):
            yield "event: thinking\n\n"
            await allow_producer_to_finish.wait()
            producer_finished.set()
            yield "event: done\n\n"

        with patch.object(chat, "stream_chat_response", fake_stream_chat_response):
            response = chat.resilient_stream_chat_response(thread_id="test-thread")
            self.assertEqual(await anext(response), "event: thinking\n\n")

            # 模拟刷新页面或网络断开：关闭 SSE 消费端，但不应取消 Agent 生产端。
            await response.aclose()
            allow_producer_to_finish.set()
            await asyncio.wait_for(producer_finished.wait(), timeout=1)

            # 让 done callback 回收全局强引用。
            await asyncio.sleep(0)
            self.assertFalse(chat._background_stream_tasks)


if __name__ == "__main__":
    unittest.main()
