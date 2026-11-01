"""Single PostgreSQL/pgvector persistence entry point.

The project intentionally has one runtime persistence path.  LangGraph's saver
and store, application rows, sandbox bindings, knowledge documents, and write
audit records all use the pool exposed here.
"""

from __future__ import annotations

import threading
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from .agent.env_utils import get_env

DATABASE_URL = get_env(
    "DATABASE_URL",
    "postgresql://erp_agent:erp_agent@localhost:5432/erp_agent",
)

_pool: ConnectionPool | None = None
_async_pool: AsyncConnectionPool | None = None
_pool_lock = threading.Lock()
_schema_lock = threading.Lock()
_schema_ready = False
_memory_search_schema_lock = threading.Lock()
_memory_search_schema_ready = False


def get_pg_pool() -> ConnectionPool:
    """Return the process-wide thread-safe connection pool."""

    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                conninfo=DATABASE_URL,
                min_size=1,
                max_size=12,
                open=True,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
    return _pool


def close_pg_pool() -> None:
    global _pool, _schema_ready, _memory_search_schema_ready
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
        _schema_ready = False
        _memory_search_schema_ready = False


async def get_async_pg_pool() -> AsyncConnectionPool:
    """Return the event-loop pool used by AsyncPostgresSaver."""

    global _async_pool
    if _async_pool is None:
        _async_pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=12,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        await _async_pool.open(wait=True)
    return _async_pool


async def close_async_pg_pool() -> None:
    global _async_pool
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None


def setup_database() -> None:
    """Create application-owned schemas and tables idempotently.

    LangGraph-owned tables are created by ``PostgresSaver.setup`` and
    ``PostgresStore.setup``.  Keeping application DDL here also lets a fresh
    compose stack boot without a second, environment-specific code path; the
    same SQL is checked in under ``migrations/postgres`` for deployments.
    """

    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        pool = get_pg_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            # This is deliberately a multi-statement bootstrap script.  The
            # pool normally prepares every statement for LangGraph/PgBouncer
            # compatibility, but PostgreSQL cannot prepare a multi-command
            # string, so bootstrap must opt out explicitly.
            cur.execute(_APPLICATION_SCHEMA_SQL, prepare=False)
        _schema_ready = True


def setup_memory_search_schema() -> None:
    """在 LangGraph Store 建表后补充记忆混合检索字段。"""

    global _memory_search_schema_ready
    if _memory_search_schema_ready:
        return
    with _memory_search_schema_lock:
        if _memory_search_schema_ready:
            return
        with get_pg_pool().connection() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS zhparser", prepare=False)
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_ts_config
                        WHERE cfgname = 'procurement_zh'
                          AND cfgnamespace = 'public'::regnamespace
                    ) THEN
                        CREATE TEXT SEARCH CONFIGURATION public.procurement_zh
                            (PARSER = zhparser);
                        ALTER TEXT SEARCH CONFIGURATION public.procurement_zh
                            ADD MAPPING FOR n, v, a, i, e, l WITH simple;
                    END IF;
                END
                $$
                """,
                prepare=False,
            )
            cur.execute("ALTER TABLE store ADD COLUMN IF NOT EXISTS search_text text")
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pg_attribute attribute
                        JOIN pg_attrdef definition
                          ON definition.adrelid = attribute.attrelid
                         AND definition.adnum = attribute.attnum
                        WHERE attribute.attrelid = 'store'::regclass
                          AND attribute.attname = 'search_document'
                          AND pg_get_expr(definition.adbin, definition.adrelid)
                              NOT LIKE '%procurement_zh%'
                    ) THEN
                        DROP INDEX IF EXISTS store_memory_search_document_idx;
                        ALTER TABLE store DROP COLUMN search_document;
                    END IF;
                END
                $$
                """,
                prepare=False,
            )
            cur.execute(
                """
                ALTER TABLE store ADD COLUMN IF NOT EXISTS search_document tsvector
                GENERATED ALWAYS AS (
                    to_tsvector(
                        'public.procurement_zh',
                        coalesce(search_text, '')
                    )
                ) STORED
                """
            )
            cur.execute("ALTER TABLE store ADD COLUMN IF NOT EXISTS embedding vector")
            cur.execute(
                "ALTER TABLE store ADD COLUMN IF NOT EXISTS embedding_hash text"
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS store_memory_search_document_idx
                ON store USING gin (search_document)
                WHERE prefix LIKE 'memories.%'
                """
            )
        _memory_search_schema_ready = True


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_pg_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_pg_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


_APPLICATION_SCHEMA_SQL = r"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS app.conversations (
    thread_id text PRIMARY KEY,
    user_id text NOT NULL,
    title text NOT NULL DEFAULT '新对话',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_user_updated_idx
    ON app.conversations (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS app.display_messages (
    thread_id text PRIMARY KEY,
    messages jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.harness_traces (
    thread_id text PRIMARY KEY,
    trace jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.sandbox_cache (
    user_id text PRIMARY KEY,
    container_name text NOT NULL UNIQUE,
    container_id text,
    state text NOT NULL,
    created_at timestamptz NOT NULL,
    claimed_at timestamptz,
    last_active_at timestamptz NOT NULL,
    active_runs integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge.documents (
    id text PRIMARY KEY,
    title text NOT NULL,
    content text NOT NULL,
    domain text NOT NULL,
    source text NOT NULL,
    version text NOT NULL,
    tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    part_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    supplier_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    embedding vector,
    embedding_backend text,
    search_document tsvector GENERATED ALWAYS AS
        (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS knowledge_documents_domain_idx
    ON knowledge.documents (domain);
CREATE INDEX IF NOT EXISTS knowledge_documents_search_idx
    ON knowledge.documents USING gin (search_document);

CREATE TABLE IF NOT EXISTS audit.write_operations (
    operation_id text PRIMARY KEY,
    idempotency_key text NOT NULL,
    tool_call_id text NOT NULL,
    thread_id text NOT NULL,
    user_id text NOT NULL,
    agent_name text NOT NULL,
    tool_name text NOT NULL,
    domain text NOT NULL,
    action text NOT NULL,
    approval_required boolean NOT NULL DEFAULT false,
    policy_id text,
    policy_version integer,
    payload_redacted jsonb NOT NULL,
    payload_hash text NOT NULL,
    status text NOT NULL,
    erp_reference text,
    result_redacted jsonb,
    result_hash text,
    last_error text,
    attempt_count integer NOT NULL DEFAULT 0,
    next_reconcile_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT write_operations_status_check CHECK (status IN (
        'CREATED', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED',
        'DISPATCHING', 'SUCCEEDED', 'FAILED', 'UNKNOWN',
        'RECONCILING', 'RECONCILED_SUCCEEDED', 'NOT_APPLIED',
        'MANUAL_REQUIRED'
    )),
    CONSTRAINT write_operations_tool_call_unique UNIQUE (thread_id, tool_call_id),
    CONSTRAINT write_operations_idempotency_unique UNIQUE (tool_name, idempotency_key)
);
ALTER TABLE audit.write_operations
    ADD COLUMN IF NOT EXISTS policy_id text,
    ADD COLUMN IF NOT EXISTS policy_version integer;
CREATE INDEX IF NOT EXISTS write_operations_user_created_idx
    ON audit.write_operations (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS write_operations_thread_created_idx
    ON audit.write_operations (thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS write_operations_reconcile_idx
    ON audit.write_operations (status, next_reconcile_at)
    WHERE status IN ('DISPATCHING', 'UNKNOWN', 'RECONCILING');

CREATE TABLE IF NOT EXISTS audit.write_audit_events (
    event_id text PRIMARY KEY,
    operation_id text NOT NULL REFERENCES audit.write_operations(operation_id),
    event_type text NOT NULL,
    user_id text NOT NULL,
    thread_id text NOT NULL,
    tool_name text NOT NULL,
    actor_id text,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS write_audit_operation_created_idx
    ON audit.write_audit_events (operation_id, created_at);
CREATE INDEX IF NOT EXISTS write_audit_user_created_idx
    ON audit.write_audit_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS write_audit_tool_event_created_idx
    ON audit.write_audit_events (tool_name, event_type, created_at DESC);

CREATE OR REPLACE FUNCTION audit.reject_audit_event_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'write_audit_events is append-only';
END;
$$;
DROP TRIGGER IF EXISTS write_audit_events_append_only ON audit.write_audit_events;
CREATE TRIGGER write_audit_events_append_only
BEFORE UPDATE OR DELETE ON audit.write_audit_events
FOR EACH ROW EXECUTE FUNCTION audit.reject_audit_event_mutation();

CREATE TABLE IF NOT EXISTS audit.reconcile_jobs (
    operation_id text PRIMARY KEY REFERENCES audit.write_operations(operation_id),
    job_status text NOT NULL DEFAULT 'PENDING',
    attempt_count integer NOT NULL DEFAULT 0,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    locked_by text,
    locked_at timestamptz,
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reconcile_jobs_status_check CHECK
        (job_status IN ('PENDING', 'RUNNING', 'DONE', 'MANUAL_REQUIRED'))
);
CREATE INDEX IF NOT EXISTS reconcile_jobs_ready_idx
    ON audit.reconcile_jobs (job_status, next_run_at);
"""
