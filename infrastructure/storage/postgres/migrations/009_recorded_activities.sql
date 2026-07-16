-- Encrypted, tenant-scoped durable activity payloads and replay records.
-- Ciphertext is produced by the separately keyed activity-store adapter;
-- PostgreSQL never receives plaintext activity inputs or outcomes.

CREATE TABLE IF NOT EXISTS event_activity_payloads (
    tenant_id                TEXT,
    tenant_scope             TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    activity_id              TEXT NOT NULL,
    payload_role             TEXT NOT NULL,
    activity_kind            TEXT NOT NULL,
    attempt                  INTEGER NOT NULL,
    contract_version         TEXT NOT NULL,
    handler_version          TEXT NOT NULL,
    idempotency_key          TEXT NOT NULL,
    security_classification  TEXT NOT NULL,
    content_type             TEXT NOT NULL,
    content_checksum         TEXT NOT NULL,
    size_bytes               BIGINT NOT NULL,
    ciphertext               BYTEA NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_scope, activity_id, payload_role),
    CONSTRAINT ck_event_activity_payloads_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_activity_payloads_role
        CHECK (payload_role IN ('input', 'output', 'error')),
    CONSTRAINT ck_event_activity_payloads_attempt
        CHECK (attempt >= 1 AND size_bytes >= 0),
    CONSTRAINT ck_event_activity_payloads_classification
        CHECK (security_classification IN ('public', 'internal', 'confidential', 'restricted')),
    CONSTRAINT ck_event_activity_payloads_checksum
        CHECK (content_checksum ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_event_activity_payloads_ciphertext
        CHECK (octet_length(ciphertext) > 0)
);

CREATE TABLE IF NOT EXISTS event_activity_records (
    tenant_id                TEXT,
    tenant_scope             TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    activity_id              TEXT NOT NULL,
    activity_kind            TEXT NOT NULL,
    attempt                  INTEGER NOT NULL,
    contract_version         TEXT NOT NULL,
    handler_version          TEXT NOT NULL,
    idempotency_key          TEXT NOT NULL,
    security_classification  TEXT NOT NULL,
    status                   TEXT NOT NULL,
    record_checksum          TEXT NOT NULL,
    size_bytes               BIGINT NOT NULL,
    ciphertext               BYTEA NOT NULL,
    accepted_at              TIMESTAMPTZ NOT NULL,
    started_at               TIMESTAMPTZ NOT NULL,
    completed_at             TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_scope, activity_id),
    CONSTRAINT ck_event_activity_records_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_activity_records_attempt
        CHECK (attempt >= 1 AND size_bytes >= 0),
    CONSTRAINT ck_event_activity_records_classification
        CHECK (security_classification IN ('public', 'internal', 'confidential', 'restricted')),
    CONSTRAINT ck_event_activity_records_status
        CHECK (status IN ('pending', 'succeeded', 'failed')),
    CONSTRAINT ck_event_activity_records_checksum
        CHECK (record_checksum ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_event_activity_records_ciphertext
        CHECK (octet_length(ciphertext) > 0),
    CONSTRAINT ck_event_activity_records_terminal
        CHECK ((status = 'pending' AND completed_at IS NULL)
            OR (status <> 'pending' AND completed_at IS NOT NULL)),
    CONSTRAINT ck_event_activity_records_time
        CHECK (accepted_at <= started_at
            AND (completed_at IS NULL OR started_at <= completed_at)
            AND updated_at >= created_at)
);

CREATE TABLE IF NOT EXISTS harness_activity_results (
    tenant_id                TEXT NOT NULL,
    tenant_scope             TEXT GENERATED ALWAYS AS (tenant_id) STORED,
    activity_id              TEXT NOT NULL,
    security_classification  TEXT NOT NULL,
    content_type             TEXT NOT NULL,
    content_checksum         TEXT NOT NULL,
    size_bytes               BIGINT NOT NULL,
    ciphertext               BYTEA NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_scope, activity_id),
    CONSTRAINT ck_harness_activity_results_tenant CHECK (btrim(tenant_id) <> ''),
    CONSTRAINT ck_harness_activity_results_classification
        CHECK (security_classification IN ('public', 'internal', 'confidential', 'restricted')),
    CONSTRAINT ck_harness_activity_results_checksum
        CHECK (content_checksum ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_harness_activity_results_content
        CHECK (size_bytes >= 0 AND octet_length(ciphertext) > 0)
);

CREATE TABLE IF NOT EXISTS event_activity_access_audit (
    audit_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id      TEXT,
    tenant_scope   TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    activity_id    TEXT NOT NULL,
    object_role    TEXT NOT NULL,
    operation      TEXT NOT NULL,
    accessed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_event_activity_access_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_activity_access_role
        CHECK (object_role IN ('record', 'input', 'output', 'error')),
    CONSTRAINT ck_event_activity_access_operation
        CHECK (operation IN ('write', 'read'))
);

CREATE INDEX IF NOT EXISTS idx_event_activity_audit_scope_activity
    ON event_activity_access_audit (tenant_scope, activity_id, audit_id);
