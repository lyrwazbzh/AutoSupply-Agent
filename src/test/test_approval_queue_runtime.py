"""Regression tests for maker-checker and externalized runtime invariants."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.audit.repository import WriteAuditRepository


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql, _params=()):
        return None

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _Cursor(self.rows)


class _Pool:
    def __init__(self, rows):
        self.rows = rows

    def connection(self):
        return _Connection(self.rows)


def _repository(rows) -> WriteAuditRepository:
    repository = object.__new__(WriteAuditRepository)
    repository.pool = _Pool(rows)
    return repository


def test_applicant_consumes_durable_decisions_in_checkpoint_order():
    repository = _repository(
        [
            {"operation_id": "op-b", "status": "REJECTED", "decision_note": "价格异常"},
            {"operation_id": "op-a", "status": "APPROVED", "decision_note": None},
        ]
    )
    assert repository.approval_decisions(
        ["op-a", "op-b"], thread_id="thread-1", requester_id="buyer"
    ) == [
        {"type": "approve"},
        {"type": "reject", "message": "价格异常"},
    ]


def test_applicant_cannot_resume_while_checker_decision_is_pending():
    repository = _repository(
        [{"operation_id": "op-a", "status": "PENDING", "decision_note": None}]
    )
    with pytest.raises(RuntimeError, match="等待独立审批"):
        repository.approval_decisions(
            ["op-a"], thread_id="thread-1", requester_id="buyer"
        )


def test_runtime_and_atomic_merge_invariants_exist_in_runtime_schema_and_migration():
    root = Path(__file__).resolve().parents[2]
    runtime_schema = (root / "src/database.py").read_text(encoding="utf-8")
    migration = (root / "migrations/postgres/0004_approval_and_runtime_state.sql").read_text(
        encoding="utf-8"
    )
    runtime_state = (root / "src/runtime_state.py").read_text(encoding="utf-8")
    preferences = (root / "src/agent/memory/postgres_search.py").read_text(encoding="utf-8")

    for sql in (runtime_schema, migration):
        assert "audit.approval_tasks" in sql
        assert "app.runtime_leases" in sql
        assert "app.sandbox_warm_pool" in sql
        assert "decided_by <> requester_id" in sql
    assert "lease_expires_at > now()" in runtime_state
    assert "pg_advisory_xact_lock" in runtime_state
    assert "def atomic_merge_preferences" in preferences
    assert "SELECT value FROM store" in preferences and "FOR UPDATE" in preferences
