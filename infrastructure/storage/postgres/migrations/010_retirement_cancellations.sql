-- Additive, tenant-scoped audit ledger for explicitly authorized retirement
-- cancellation. Delivery rows remain durable and are terminally disposed;
-- this ledger preserves each prior nonterminal state and the exact authority.

CREATE TABLE IF NOT EXISTS event_retirement_cancellation_reports (
    cancellation_id                TEXT NOT NULL,
    tenant_id                      TEXT,
    tenant_scope                   TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    subscription_id                TEXT NOT NULL,
    subscription_version           INTEGER NOT NULL,
    requested_at                   TIMESTAMPTZ NOT NULL,
    cancelled_at                   TIMESTAMPTZ NOT NULL,
    operator_id                    TEXT NOT NULL,
    operator_reason                TEXT NOT NULL,
    authorization_evidence_ref     TEXT NOT NULL,
    item_limit                     INTEGER NOT NULL,
    cancelled_count                INTEGER NOT NULL,
    remaining_nonterminal_count    BIGINT NOT NULL,
    remaining_nonterminal_count_truncated BOOLEAN NOT NULL,
    CONSTRAINT pk_event_retirement_cancellation_reports
        PRIMARY KEY (tenant_scope, cancellation_id),
    CONSTRAINT uq_event_retirement_cancellation_reports_identity
        UNIQUE (
            tenant_scope,
            cancellation_id,
            subscription_id,
            subscription_version
        ),
    CONSTRAINT fk_event_retirement_cancellation_reports_subscription
        FOREIGN KEY (subscription_id, subscription_version, tenant_scope)
        REFERENCES event_subscriptions (
            subscription_id,
            subscription_version,
            tenant_scope
        )
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_retirement_cancellation_reports_identity
        CHECK (btrim(cancellation_id) <> '' AND subscription_version >= 1),
    CONSTRAINT ck_event_retirement_cancellation_reports_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_retirement_cancellation_reports_time
        CHECK (cancelled_at >= requested_at),
    CONSTRAINT ck_event_retirement_cancellation_reports_operator
        CHECK (btrim(operator_id) <> '' AND btrim(operator_reason) <> ''),
    CONSTRAINT ck_event_retirement_cancellation_reports_authorization
        CHECK (
            btrim(authorization_evidence_ref) <> ''
            AND char_length(authorization_evidence_ref) <= 512
        ),
    CONSTRAINT ck_event_retirement_cancellation_reports_bounds
        CHECK (
            item_limit BETWEEN 1 AND 1000
            AND cancelled_count BETWEEN 0 AND item_limit
            AND remaining_nonterminal_count >= 0
            AND (
                (
                    NOT remaining_nonterminal_count_truncated
                    AND remaining_nonterminal_count <= item_limit
                )
                OR (
                    remaining_nonterminal_count_truncated
                    AND remaining_nonterminal_count = item_limit + 1
                )
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_event_retirement_cancellation_reports_subscription
    ON event_retirement_cancellation_reports (
        tenant_scope,
        subscription_id,
        subscription_version,
        requested_at,
        cancellation_id
    );

CREATE TABLE IF NOT EXISTS event_retirement_cancellation_items (
    tenant_id                 TEXT,
    tenant_scope              TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    cancellation_id           TEXT NOT NULL,
    delivery_id               TEXT NOT NULL,
    event_id                  TEXT NOT NULL,
    stream_id                 TEXT NOT NULL,
    stream_sequence           BIGINT NOT NULL,
    subscription_id           TEXT NOT NULL,
    subscription_version      INTEGER NOT NULL,
    delivery_generation       INTEGER NOT NULL,
    previous_state            TEXT NOT NULL,
    previous_attempt_count    INTEGER NOT NULL,
    previous_reason_class     TEXT,
    terminal_state            TEXT NOT NULL,
    cancelled_at              TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_event_retirement_cancellation_items
        PRIMARY KEY (tenant_scope, cancellation_id, delivery_id),
    CONSTRAINT uq_event_retirement_cancellation_items_delivery
        UNIQUE (delivery_id),
    CONSTRAINT fk_event_retirement_cancellation_items_report
        FOREIGN KEY (
            tenant_scope,
            cancellation_id,
            subscription_id,
            subscription_version
        )
        REFERENCES event_retirement_cancellation_reports (
            tenant_scope,
            cancellation_id,
            subscription_id,
            subscription_version
        )
        ON DELETE RESTRICT,
    CONSTRAINT fk_event_retirement_cancellation_items_delivery
        FOREIGN KEY (delivery_id)
        REFERENCES event_deliveries (delivery_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_retirement_cancellation_items_identity
        CHECK (
            btrim(delivery_id) <> ''
            AND btrim(event_id) <> ''
            AND btrim(stream_id) <> ''
            AND stream_sequence >= 1
            AND subscription_version >= 1
            AND delivery_generation >= 1
            AND previous_attempt_count >= 0
        ),
    CONSTRAINT ck_event_retirement_cancellation_items_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_retirement_cancellation_items_disposition
        CHECK (
            (
                previous_state = 'pending'
                AND previous_attempt_count = 0
            )
            OR (
                previous_state IN ('claimed', 'retry_wait')
                AND previous_attempt_count >= 1
            )
        ),
    CONSTRAINT ck_event_retirement_cancellation_items_terminal
        CHECK (terminal_state = 'dropped')
);

CREATE INDEX IF NOT EXISTS idx_event_retirement_cancellation_items_report
    ON event_retirement_cancellation_items (
        tenant_scope,
        cancellation_id,
        stream_id,
        stream_sequence,
        delivery_generation,
        delivery_id
    );
