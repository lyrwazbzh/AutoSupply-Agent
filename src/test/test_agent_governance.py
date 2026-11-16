import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.interceptors import MCPToolCallRequest

from src.agent.approval import approval_policy_registry
from src.agent.main_agent import SKILLS_DIR, _load_skills_index, _main_tool_surface
from src.agent.memory.extractor import summarize_episode
from src.agent.memory.keeper import MemoryKeeper
from src.agent.memory.types import MemorySearchStatus
from src.agent.runtime_context import bind_runtime, reset_runtime
from src.agent.subagents.loader import resolve_subagent_tools
from src.agent.tools.knowledge_tools import ingest_business_knowledge
from src.agent.tools.mcp_client import _request_bearer_token_interceptor
from src.agent.tools.web_fetch import install_skill
from src.api_view.agent_loader import AgentLoader
from src.api_view.api.chat import _pending_approval_actions
from src.test.test_memory_layer import FakeStore


def test_approval_permissions_are_enforced_per_pending_tool():
    missing = approval_policy_registry.missing_approver_permissions(
        ["order_create", "order_receive"],
        {"assistant:use", "erp:order:create"},
    )
    assert set(missing) == {"order_create", "order_receive"}
    assert approval_policy_registry.missing_approver_permissions(
        ["order_create", "order_receive"],
        {"erp:order:approve"},
    ) == {}


def test_pending_approval_operations_come_from_checkpoint_state():
    state = SimpleNamespace(tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value={
        "action_requests": [
            {"name": "order_create", "args": {"operation_id": "op-1"}},
            {"name": "order_receive", "args": {"operation_id": "op-2"}},
        ]
    })])])
    assert _pending_approval_actions(state) == [
        {"tool_name": "order_create", "operation_id": "op-1"},
        {"tool_name": "order_receive", "operation_id": "op-2"},
    ]


def test_knowledge_and_skill_mutations_have_runtime_permission_guard():
    tokens = bind_runtime("viewer", None, permissions=frozenset())
    try:
        knowledge = ingest_business_knowledge.invoke({
            "title": "test",
            "content": "content",
            "domain": "procurement_sop",
            "source": "unit-test",
        })
        skill = install_skill.invoke({"url": "https://example.com/skill.md"})
    finally:
        reset_runtime(tokens)
    assert "assistant:knowledge:write" in knowledge
    assert "assistant:skill:install" in skill


def test_subagent_tool_resolution_is_exact_only():
    tools = [SimpleNamespace(name=name) for name in (
        "order_create", "order_page", "reorder_item"
    )]
    specs = resolve_subagent_tools(
        [{"name": "order", "description": "d", "system_prompt": "p", "tools": ["order"]}],
        tools,
    )
    assert specs[0]["tools"] == []


def test_subagent_tool_surfaces_remain_partitioned():
    tools = [SimpleNamespace(name=name) for name in (
        "part_query", "order_create", "generate_chart"
    )]
    specs = resolve_subagent_tools(
        [
            {
                "name": "analyst",
                "description": "d",
                "system_prompt": "p",
                "tools": ["part_query", "generate_chart"],
            },
            {
                "name": "order",
                "description": "d",
                "system_prompt": "p",
                "tools": ["part_query", "order_create"],
            },
        ],
        tools,
    )
    assert [tool.name for tool in specs[0]["tools"]] == [
        "part_query", "generate_chart"
    ]
    assert [tool.name for tool in specs[1]["tools"]] == [
        "part_query", "order_create"
    ]


def test_main_agent_keeps_full_authorized_tool_surface():
    catalog = [
        SimpleNamespace(name="part_query"),
        SimpleNamespace(name="order_create"),
        SimpleNamespace(name="generate_chart"),
    ]
    main_tools = _main_tool_surface(catalog)
    assert main_tools == catalog
    assert main_tools is not catalog
    assert "order_create" in {
        tool.name for tool in main_tools
    } & set(approval_policy_registry.main_interrupt_on())


def test_skill_prompt_is_index_only_and_points_to_sandbox_files():
    index = _load_skills_index(SKILLS_DIR)
    assert "Skills 索引" in index
    assert "/skills/procurement/price-comparison/SKILL.md" in index
    assert "## 操作步骤" not in index
    assert len(index) < 5000


def test_episode_summary_preserves_procurement_state():
    messages = [
        HumanMessage(content="创建采购单，必须使用现有报价，不要修改数量。"),
        AIMessage(content="", tool_calls=[{
            "id": "call-create",
            "name": "order_create",
            "args": {
                "orderNumber": "PO20261113001",
                "supplierCode": "SUP-001",
                "operation_id": "op-create-001",
                "idempotencyKey": "idem-001",
                "status": "PENDING",
                "details": [{"partCode": "BRK-001", "quantity": 10}],
            },
        }]),
        ToolMessage(
            content='{"code":200,"data":{"orderNumber":"PO20261113001","status":"PENDING"}}',
            tool_call_id="call-create",
            name="order_create",
        ),
        AIMessage(content="", tool_calls=[{
            "id": "call-receive",
            "name": "order_receive",
            "args": {"orderNumber": "PO20261113001", "operation_id": "op-receive-001"},
        }]),
    ]
    digest = summarize_episode(messages, thread_id="thread-1")
    structured = digest["structured"]
    assert structured["order_numbers"] == ["PO20261113001"]
    assert structured["part_codes"] == ["BRK-001"]
    assert structured["supplier_codes"] == ["SUP-001"]
    assert structured["operation_ids"] == ["op-create-001", "op-receive-001"]
    assert structured["idempotency_keys"] == ["idem-001"]
    assert structured["pending_approvals"] == ["order_receive"]
    assert structured["confirmed_constraints"]
    assert "order:PO20261113001" in digest["entities"]


def test_memory_no_result_and_service_failure_are_distinct():
    keeper = MemoryKeeper(FakeStore(), "u1")
    with patch.object(keeper, "_cold_lanes", return_value=([], [])):
        no_result = keeper.search_result("不存在的订单")
    with patch.object(keeper, "_cold_lanes", side_effect=RuntimeError("db down")):
        unavailable = keeper.search_result("历史订单")
        unavailable_text = keeper.search_text("历史订单")
    assert no_result.status == MemorySearchStatus.NO_RESULT
    assert unavailable.status == MemorySearchStatus.UNAVAILABLE
    assert "暂时不可用" in unavailable_text


def test_mcp_bearer_token_is_injected_per_request():
    captured = {}

    async def handler(request):
        captured.update(request.headers or {})
        return "ok"

    async def run():
        tokens = bind_runtime("u1", None, access_token="fresh-token", permissions=frozenset())
        try:
            request = MCPToolCallRequest(name="part_query", args={}, server_name="erp")
            return await _request_bearer_token_interceptor(request, handler)
        finally:
            reset_runtime(tokens)

    assert asyncio.run(run()) == "ok"
    assert captured == {"Authorization": "Bearer fresh-token"}


def _isolated_loader() -> AgentLoader:
    class FakeRuntimeState:
        def __init__(self):
            self.version = 0
            self.released = []

        def acquire_session(self, user_id, *, owner_id, ttl_seconds, metadata=None):
            self.version += 1
            return SimpleNamespace(
                resource_type="agent_session",
                resource_key=user_id,
                owner_id=owner_id,
                token=f"lease-{self.version}",
                version=self.version,
            )

        def release(self, _handle):
            self.released.append(_handle.token)
            return True

    loader = object.__new__(AgentLoader)
    loader.agent = None
    loader._store = object()
    loader._checkpointer = object()
    loader._write_audit_repository = object()
    loader._runtime_state_repository = FakeRuntimeState()
    loader.instance_id = "test-instance"
    loader._sessions = {}
    loader._sessions_lock = None
    loader._session_build_locks = {}
    loader._ensure_resources = AsyncMock()
    builds = []

    def build(user_id, username, token, roles, permissions, authz_version):
        agent = object()
        builds.append((token, agent))
        return agent, SimpleNamespace(), SimpleNamespace(model_dump=lambda **_: {})

    loader._build_agent_for_user = build
    loader._test_builds = builds
    return loader


def test_agent_session_reuses_capability_graph_across_token_refresh():
    async def run():
        loader = _isolated_loader()
        first = await loader.get_session(
            "u1", "buyer", access_token="token-1",
            roles=frozenset({"PURCHASER"}),
            permissions=frozenset({"assistant:use"}), authz_version=3,
        )
        refreshed = await loader.get_session(
            "u1", "buyer", access_token="token-2",
            roles=frozenset({"PURCHASER"}),
            permissions=frozenset({"assistant:use"}), authz_version=3,
        )
        changed = await loader.get_session(
            "u1", "buyer", access_token="token-3",
            roles=frozenset({"PURCHASER"}),
            permissions=frozenset({"assistant:use", "erp:order:create"}), authz_version=4,
        )
        return loader, first, refreshed, changed

    loader, first, refreshed, changed = asyncio.run(run())
    assert first is refreshed
    assert changed is not first
    assert len(loader._test_builds) == 2
    assert not hasattr(first, "access_token")


def test_agent_session_ttl_evicts_idle_session_but_not_active_session():
    async def run():
        loader = _isolated_loader()
        with patch("src.api_view.agent_loader.AGENT_SESSION_TTL_SECONDS", 10):
            idle = await loader.get_session("idle")
            active = await loader.get_session("active")
            idle.last_accessed_at -= 20
            active.last_accessed_at -= 20
            await active.run_lock.acquire()
            try:
                await loader.get_session("incoming")
            finally:
                active.run_lock.release()
        return loader

    loader = asyncio.run(run())
    assert "idle" not in loader._sessions
    assert "active" in loader._sessions
    assert "incoming" in loader._sessions


def test_agent_session_ttl_rebuilds_same_user_after_expiry():
    async def run():
        loader = _isolated_loader()
        with patch("src.api_view.agent_loader.AGENT_SESSION_TTL_SECONDS", 10):
            first = await loader.get_session("u1", access_token="token-1")
            first.last_accessed_at -= 20
            rebuilt = await loader.get_session("u1", access_token="token-2")
        return loader, first, rebuilt

    loader, first, rebuilt = asyncio.run(run())
    assert rebuilt is not first
    assert len(loader._test_builds) == 2
    assert loader._runtime_state_repository.released == []


def test_memory_unique_active_constraint_is_in_runtime_and_migration():
    root = Path(__file__).resolve().parents[2]
    runtime_sql = (root / "src/database.py").read_text(encoding="utf-8")
    migration_sql = root / "migrations/postgres/0003_memory_semantic_invariants.sql"
    migration = migration_sql.read_text(encoding="utf-8")
    assert "store_one_active_semantic_key_idx" in runtime_sql
    assert "store_one_active_semantic_key_idx" in migration
    assert "pg_advisory_xact_lock" in (
        root / "src/agent/memory/postgres_search.py"
    ).read_text(encoding="utf-8")
