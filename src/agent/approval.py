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

    def missing_approver_permissions(
        self,
        tool_names: Iterable[str],
        permissions: Iterable[str],
    ) -> dict[str, tuple[str, ...]]:
        """返回当前主体无权审批的工具及其可选权限。

        一个策略中的多个 ``approver_permissions`` 表示可选权限（满足其一即可）；
        同一批中断里的每个受保护工具都必须分别通过校验。
        """
        granted = {str(permission) for permission in permissions}
        missing: dict[str, tuple[str, ...]] = {}
        for raw_name in tool_names:
            tool_name = str(raw_name or "").lower()
            policy = self.get(tool_name)
            if not policy or not policy.requires_approval:
                continue
            required = policy.approver_permissions
            if required and not any(permission in granted for permission in required):
                missing[tool_name] = required
        return missing


approval_policy_registry = ApprovalPolicyRegistry(
    (
        ApprovalPolicy(
            policy_id="order-create-v1",
            tool_name="order_create",
            requires_approval=True,
            description="采购订单创建审批：请确认供应商、零部件、数量和金额。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="order-update-v1",
            tool_name="order_update",
            requires_approval=True,
            description="采购订单修改审批：请确认修改内容。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="order-status-v1",
            tool_name="order_update_status",
            requires_approval=True,
            description="订单状态变更确认：状态变更不可逆，请确认。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="order-receive-v1",
            tool_name="order_receive",
            requires_approval=True,
            description="采购收货确认：确认后将自动入库并生成库存流水。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="replenishment-create-v1",
            tool_name="replenishment_create",
            requires_approval=True,
            description="补货任务创建确认：请核对零件、建议数量和供应商。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="replenishment-inspect-v1",
            tool_name="replenishment_inspect",
            requires_approval=True,
            description="库存巡检确认：执行后可能批量生成补货任务。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="replenishment-order-v1",
            tool_name="replenishment_create_order",
            requires_approval=True,
            description="补货转采购单确认：请核对供应商、数量和预计到货日。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="replenishment-complete-v1",
            tool_name="replenishment_complete",
            requires_approval=True,
            description="补货任务完成确认。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="replenishment-cancel-v1",
            tool_name="replenishment_cancel",
            requires_approval=True,
            description="补货任务取消确认。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="purchase-return-create-v1",
            tool_name="purchase_return_create",
            requires_approval=True,
            description="采购退货创建确认：请核对采购单、零件、数量和原因。",
            approver_permissions=("erp:order:approve",),
        ),
        ApprovalPolicy(
            policy_id="purchase-return-confirm-v1",
            tool_name="purchase_return_confirm",
            requires_approval=True,
            description="采购退货确认：确认后将扣减库存并生成库存流水。",
            approver_permissions=("erp:order:approve",),
        ),
    )
)
