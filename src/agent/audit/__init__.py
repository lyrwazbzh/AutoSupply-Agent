"""Unified result and ERP write auditing."""

from typing import TYPE_CHECKING

from .registry import WRITE_TOOL_SPECS, WriteToolSpec, is_erp_write_tool
from .result import AuditFinding, AuditResult, ResultAuditor

if TYPE_CHECKING:
    from .repository import WriteAuditRepository


def __getattr__(name: str):
    """Keep the DB-backed repository lazy for registry/result-only consumers."""
    if name == "WriteAuditRepository":
        from .repository import WriteAuditRepository

        return WriteAuditRepository
    raise AttributeError(name)

__all__ = [
    "AuditFinding",
    "AuditResult",
    "ResultAuditor",
    "WRITE_TOOL_SPECS",
    "WriteAuditRepository",
    "WriteToolSpec",
    "is_erp_write_tool",
]
