"""The only source of truth for ERP tools with business side effects."""

from __future__ import annotations

from dataclasses import dataclass

from ..approval import approval_policy_registry


@dataclass(frozen=True)
class WriteToolSpec:
    domain: str
    action: str
    requires_approval: bool = False


_WRITE_TOOL_METADATA = {
    "order_create": ("order", "create"),
    "order_update": ("order", "update"),
    "order_update_status": ("order", "update_status"),
    "inventory_inbound": ("inventory", "inbound"),
    "inventory_outbound": ("inventory", "outbound"),
    "supplier_create": ("supplier", "create"),
    "supplier_update_status": ("supplier", "update_status"),
    "part_create": ("part", "create"),
}


# Approval requirements are compiled from ApprovalPolicyRegistry rather than
# maintained as a second hand-written policy list.
WRITE_TOOL_SPECS: dict[str, WriteToolSpec] = {
    tool_name: WriteToolSpec(
        domain,
        action,
        approval_policy_registry.requires_approval(tool_name),
    )
    for tool_name, (domain, action) in _WRITE_TOOL_METADATA.items()
}


def is_erp_write_tool(tool_name: str) -> bool:
    return str(tool_name or "").lower() in WRITE_TOOL_SPECS
