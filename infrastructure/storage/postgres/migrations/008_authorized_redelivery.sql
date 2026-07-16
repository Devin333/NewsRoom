-- Additive audit ledger for tenant-scoped authorized redelivery.
-- Source events, prior deliveries, dead letters, and inbox entries remain
-- immutable; every selected event-consumer pair receives a new delivery
-- generation linked to one idempotent operator request.

CREATE TABLE IF NOT EXISTS event_redelivery_reports (
    redelivery_id                 TEXT NOT NULL,
    tenant_id                     TEXT,
    tenant_scope                  TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    subscription_id               TEXT NOT NULL,
    subscription_version          INTEGER NOT NULL,
    source_stream_id              TEXT NOT NULL,
    from_sequence                 BIGINT NOT NULL,
    requested_through_sequence    BIGINT,
    through_sequence              BIGINT NOT NULL,
    captured_high_watermark       BIGINT NOT NULL,
    requested_at                  TIMESTAMPTZ NOT NULL,
    scheduled_at                  TIMESTAMPTZ NOT NULL,
    operator_id                   TEXT NOT NULL,
    operator_reason               TEXT NOT NULL,
    authorization_evidence_ref    TEXT NOT NULL,
    CONSTRAINT pk_event_redelivery_reports
        PRIMARY KEY (tenant_scope, redelivery_id),
    CONSTRAINT fk_event_redelivery_reports_subscription
        FOREIGN KEY (subscription_id, subscription_version, tenant_scope)
        REFERENCES event_subscriptions (
            subscription_id,
            subscription_version,
            tenant_scope
        )
        ON DELETE RESTRICT,
    CONSTRAINT fk_event_redelivery_reports_stream
        FOREIGN KEY (tenant_scope, source_stream_id)
        REFERENCES event_stream_sequences (tenant_scope, stream_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_redelivery_reports_identity
        CHECK (
            btrim(redelivery_id) <> ''
            AND btrim(source_stream_id) <> ''
            AND subscription_version >= 1
        ),
    CONSTRAINT ck_event_redelivery_reports_range
        CHECK (
            from_sequence >= 1
            AND through_sequence >= from_sequence
            AND through_sequence - from_sequence < 1000
            AND captured_high_watermark >= through_sequence
            AND (
                requested_through_sequence IS NULL
                OR requested_through_sequence = through_sequence
            )
        ),
    CONSTRAINT ck_event_redelivery_reports_operator
        CHECK (btrim(operator_id) <> '' AND btrim(operator_reason) <> ''),
    CONSTRAINT ck_event_redelivery_reports_authorization
        CHECK (
            btrim(authorization_evidence_ref) <> ''
            AND char_length(authorization_evidence_ref) <= 512
        ),
    CONSTRAINT ck_event_redelivery_reports_time
        CHECK (scheduled_at >= requested_at)
);

CREATE INDEX IF NOT EXISTS idx_event_redelivery_reports_scope_stream
    ON event_redelivery_reports (
        tenant_scope,
        source_stream_id,
        subscription_id,
        subscription_version,
        requested_at,
        redelivery_id
    );

CREATE TABLE IF NOT EXISTS event_redelivery_items (
    tenant_id               TEXT,
    tenant_scope            TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    redelivery_id           TEXT NOT NULL,
    event_id                TEXT NOT NULL,
    stream_id               TEXT NOT NULL,
    stream_sequence         BIGINT NOT NULL,
    subscription_id         TEXT NOT NULL,
    subscription_version    INTEGER NOT NULL,
    delivery_id             TEXT NOT NULL,
    delivery_generation     INTEGER NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_event_redelivery_items
        PRIMARY KEY (
            tenant_scope,
            redelivery_id,
            event_id,
            subscription_id,
            subscription_version
        ),
    CONSTRAINT uq_event_redelivery_items_delivery
        UNIQUE (delivery_id),
    CONSTRAINT fk_event_redelivery_items_report
        FOREIGN KEY (tenant_scope, redelivery_id)
        REFERENCES event_redelivery_reports (tenant_scope, redelivery_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_event_redelivery_items_delivery
        FOREIGN KEY (delivery_id)
        REFERENCES event_deliveries (delivery_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_redelivery_items_identity
        CHECK (
            btrim(event_id) <> ''
            AND btrim(stream_id) <> ''
            AND stream_sequence >= 1
            AND subscription_version >= 1
            AND delivery_generation >= 2
        )
);

CREATE INDEX IF NOT EXISTS idx_event_redelivery_items_report_sequence
    ON event_redelivery_items (
        tenant_scope,
        redelivery_id,
        stream_sequence,
        event_id
    );
