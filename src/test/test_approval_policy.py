from src.agent.approval import approval_policy_registry
from src.agent.audit.registry import WRITE_TOOL_SPECS
from src.agent.subagents.loader import load_subagent_configs, resolve_subagent_tools


def test_central_policy_covers_all_approval_writes_without_edit():
    policy = approval_policy_registry.main_interrupt_on()

    assert set(policy) == {"order_create", "order_update", "order_update_status"}
    assert all(config["allowed_decisions"] == ["approve", "reject"] for config in policy.values())
    assert all(WRITE_TOOL_SPECS[name].requires_approval for name in policy)


def test_subagent_receives_policy_subset_from_registry():
    configs = load_subagent_configs()
    all_tools = []
    specs = resolve_subagent_tools(
        configs,
        all_tools,
        approval_policy=approval_policy_registry,
    )

    assert all("interrupt_on" not in spec for spec in specs)
