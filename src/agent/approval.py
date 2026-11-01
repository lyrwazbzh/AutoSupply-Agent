"""Single source of truth for protected ERP write approvals.

Agent configuration describes capabilities and prompts.  Approval is a business
governance concern, so it is compiled here once and then projected into the
main-agent and sub-agent runtime configurations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ApprovalPolicy:
    policy_id: str
    tool_name: str
    requires_approval: bool
    allowed_decisions: tuple[str, ...] = ("approve", "reject")
    description: str = ""
    approver_permissions: tuple[str, ...] = ()
    version: int = 1

    def to_interrupt_config(self) -> dict:
        """Return the format consumed by DeepAgents HITL."""
        config = {"allowed_decisions": list(self.allowed_decisions)}
        if self.description:
            config["description"] = self.description
        return config


class ApprovalPolicyRegistry:
    """Immutable registry for all approval-governed write tools."""

    def __init__(self, policies: Iterable[ApprovalPolicy]) -> None:
        self._policies = {policy.tool_name: policy for policy in policies}

    def get(self, tool_name: str) -> ApprovalPolicy | None:
        return self._policies.get(str(tool_name or "").lower())

    def requires_approval(self, tool_name: str) -> bool:
        policy = self.get(tool_name)
        return bool(policy and policy.requires_approval)

    def main_interrupt_on(self) -> dict[str, dict]:
        """Compile the policy covering direct main-agent write calls."""
        return {
            tool_name: policy.to_interrupt_config()
            for tool_name, policy in self._policies.items()
            if policy.requires_approval
        }

    def subset_for_tools(self, tool_names: Iterable[str]) -> dict[str, dict]:
        """Compile the policy subset visible to one delegated agent."""
        names = {str(name or "").lower() for name in tool_names}
        return {
            tool_name: policy.to_interrupt_config()
            for tool_name, policy in self._policies.items()
            if policy.requires_approval and tool_name in names
        }

    def policy_version(self, tool_name: str) -> int | None:
        policy = self.get(tool_name)
        return policy.version if policy else None


approval_policy_registry = ApprovalPolicyRegistry(
    (
        ApprovalPolicy(
            policy_id="order-create-v1",
            tool_name="order_create",
            requires_approval=True,
            description="采购订单创建审批：请确认供应商、零部件、数量和金额。",
            approver_permissions=("order.approve",),
        ),
        ApprovalPolicy(
            policy_id="order-update-v1",
            tool_name="order_update",
            requires_approval=True,
            description="采购订单修改审批：请确认修改内容。",
            approver_permissions=("order.approve",),
        ),
        ApprovalPolicy(
            policy_id="order-status-v1",
            tool_name="order_update_status",
            requires_approval=True,
            description="订单状态变更确认：状态变更不可逆，请确认。",
            approver_permissions=("order.status.approve",),
        ),
    )
)
