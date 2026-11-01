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
