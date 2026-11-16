"""The only source of truth for ERP tools with business side effects."""

from __future__ import annotations

from dataclasses import dataclass

from ..approval import approval_policy_registry


@dataclass(frozen=True)
class WriteToolSpec:
    domain: str
    action: str
    required_permission: str
    requires_approval: bool = False


_WRITE_TOOL_METADATA = {
    "order_create": ("order", "create", "erp:order:create"),
    "order_update": ("order", "update", "erp:order:update"),
    "order_update_status": ("order", "update_status", "erp:order:status"),
    "inventory_inbound": ("inventory", "inbound", "erp:inventory:inbound"),
    "inventory_outbound": ("inventory", "outbound", "erp:inventory:outbound"),
    "supplier_create": ("supplier", "create", "erp:supplier:write"),
    "supplier_update_status": ("supplier", "update_status", "erp:supplier:status"),
    "part_create": ("part", "create", "erp:part:write"),
    "order_receive": ("order", "receive", "erp:order:receive"),
    "replenishment_create": ("replenishment", "create", "erp:replenishment:manage"),
    "replenishment_inspect": ("replenishment", "inspect", "erp:replenishment:manage"),
    "replenishment_create_order": (
        "replenishment",
        "create_order",
        "erp:replenishment:manage",
    ),
    "replenishment_complete": (
        "replenishment",
        "complete",
        "erp:replenishment:manage",
    ),
    "replenishment_cancel": (
        "replenishment",
        "cancel",
        "erp:replenishment:manage",
    ),
    "purchase_return_create": ("purchase_return", "create", "erp:order:return"),
    "purchase_return_confirm": ("purchase_return", "confirm", "erp:order:return"),
}


# Approval requirements are compiled from ApprovalPolicyRegistry rather than
# maintained as a second hand-written policy list.
WRITE_TOOL_SPECS: dict[str, WriteToolSpec] = {
    tool_name: WriteToolSpec(
        domain,
        action,
        permission,
        approval_policy_registry.requires_approval(tool_name),
    )
    for tool_name, (domain, action, permission) in _WRITE_TOOL_METADATA.items()
}


def is_erp_write_tool(tool_name: str) -> bool:
    return str(tool_name or "").lower() in WRITE_TOOL_SPECS
