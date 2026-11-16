-- Independent maker-checker queue and distributed runtime coordination.

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.approval_tasks (
    task_id text PRIMARY KEY,
    operation_id text NOT NULL UNIQUE
        REFERENCES audit.write_operations(operation_id),
    requester_id text NOT NULL,
    status text NOT NULL DEFAULT 'PENDING',
    decided_by text,
    decision_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT approval_tasks_status_check
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CONSTRAINT approval_tasks_maker_checker_check
        CHECK (decided_by IS NULL OR decided_by <> requester_id)
);
CREATE INDEX IF NOT EXISTS approval_tasks_pending_created_idx
    ON audit.approval_tasks (created_at, task_id)
    WHERE status = 'PENDING';

-- Backfill operations that were waiting before this migration was installed.
INSERT INTO audit.approval_tasks(task_id, operation_id, requester_id, status)
SELECT 'approval:' || operation_id, operation_id, user_id, 'PENDING'
FROM audit.write_operations
WHERE approval_required = true AND status = 'PENDING_APPROVAL'
ON CONFLICT (operation_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS app.runtime_leases (
    resource_type text NOT NULL,
    resource_key text NOT NULL,
    owner_id text NOT NULL,
    lease_token text NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (resource_type, resource_key),
    UNIQUE (lease_token)
);
CREATE INDEX IF NOT EXISTS runtime_leases_expiry_idx
    ON app.runtime_leases (lease_expires_at);

ALTER TABLE app.sandbox_cache
    ADD COLUMN IF NOT EXISTS assignment_owner_id text,
    ADD COLUMN IF NOT EXISTS assignment_version bigint NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS app.sandbox_warm_pool (
    container_name text PRIMARY KEY,
    owner_id text NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sandbox_warm_pool_expiry_idx
    ON app.sandbox_warm_pool (lease_expires_at);
