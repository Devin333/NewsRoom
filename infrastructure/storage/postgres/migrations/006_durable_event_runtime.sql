-- Additive PostgreSQL 16+ schema for the canonical durable event runtime.
-- Empty tenant_scope represents an unscoped event. Application tenant ids are
-- non-empty, so the generated value makes nullable tenant identity safe in
-- primary, foreign-key, and unique constraints.

CREATE TABLE IF NOT EXISTS event_stream_sequences (
    tenant_id       TEXT,
    tenant_scope    TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    stream_id       TEXT NOT NULL,
    last_sequence   BIGINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_event_stream_sequences
        PRIMARY KEY (tenant_scope, stream_id),
    CONSTRAINT ck_event_stream_sequences_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_stream_sequences_stream
        CHECK (btrim(stream_id) <> ''),
    CONSTRAINT ck_event_stream_sequences_value
        CHECK (last_sequence >= 0),
    CONSTRAINT ck_event_stream_sequences_time
        CHECK (updated_at >= created_at)
);

CREATE TABLE IF NOT EXISTS durable_events (
    event_id                    TEXT PRIMARY KEY,
    tenant_id                   TEXT,
    tenant_scope                TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    stream_id                   TEXT NOT NULL,
    stream_sequence             BIGINT NOT NULL,
    envelope_schema             TEXT NOT NULL,
    event_type                  TEXT NOT NULL,
    data_schema                 TEXT NOT NULL,
    source                      TEXT NOT NULL,
    subject                     TEXT,
    occurred_at                 TIMESTAMPTZ NOT NULL,
    observed_at                 TIMESTAMPTZ NOT NULL,
    correlation_id              TEXT,
    causation_id                TEXT,
    business_context            JSONB NOT NULL DEFAULT '{}'::jsonb,
    producer                    JSONB NOT NULL,
    trace_context               JSONB,
    security_classification     TEXT NOT NULL DEFAULT 'internal',
    content_type                TEXT NOT NULL,
    payload                     JSONB,
    payload_ref                 JSONB,
    extensions                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_checksum            TEXT NOT NULL,
    record_checksum             TEXT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_durable_events_identity_scope
        UNIQUE (event_id, tenant_scope),
    CONSTRAINT uq_durable_events_stream_sequence
        UNIQUE (tenant_scope, stream_id, stream_sequence),
    CONSTRAINT uq_durable_events_delivery_ref
        UNIQUE (event_id, tenant_scope, stream_id, stream_sequence),
    CONSTRAINT fk_durable_events_stream
        FOREIGN KEY (tenant_scope, stream_id)
        REFERENCES event_stream_sequences (tenant_scope, stream_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_durable_events_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_durable_events_required_text
        CHECK (
            btrim(event_id) <> ''
            AND btrim(stream_id) <> ''
            AND btrim(envelope_schema) <> ''
            AND btrim(event_type) <> ''
            AND btrim(data_schema) <> ''
            AND btrim(source) <> ''
            AND btrim(content_type) <> ''
        ),
    CONSTRAINT ck_durable_events_optional_text
        CHECK (
            (subject IS NULL OR btrim(subject) <> '')
            AND (correlation_id IS NULL OR btrim(correlation_id) <> '')
            AND (causation_id IS NULL OR btrim(causation_id) <> '')
        ),
    CONSTRAINT ck_durable_events_sequence
        CHECK (stream_sequence >= 1),
    CONSTRAINT ck_durable_events_security_classification
        CHECK (security_classification IN ('public', 'internal', 'confidential', 'restricted')),
    CONSTRAINT ck_durable_events_payload_choice
        CHECK ((payload IS NULL) <> (payload_ref IS NULL)),
    CONSTRAINT ck_durable_events_payload_object
        CHECK (payload IS NULL OR jsonb_typeof(payload) = 'object'),
    CONSTRAINT ck_durable_events_payload_ref_object
        CHECK (payload_ref IS NULL OR jsonb_typeof(payload_ref) = 'object'),
    CONSTRAINT ck_durable_events_business_context_object
        CHECK (jsonb_typeof(business_context) = 'object'),
    CONSTRAINT ck_durable_events_producer_object
        CHECK (jsonb_typeof(producer) = 'object'),
    CONSTRAINT ck_durable_events_trace_object
        CHECK (trace_context IS NULL OR jsonb_typeof(trace_context) = 'object'),
    CONSTRAINT ck_durable_events_extensions_object
        CHECK (jsonb_typeof(extensions) = 'object'),
    CONSTRAINT ck_durable_events_content_checksum
        CHECK (content_checksum ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_durable_events_record_checksum
        CHECK (record_checksum ~ '^sha256:[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_durable_events_stream_observed
    ON durable_events (tenant_scope, stream_id, observed_at, stream_sequence);
CREATE INDEX IF NOT EXISTS idx_durable_events_type_sequence
    ON durable_events (tenant_scope, event_type, stream_id, stream_sequence);
CREATE INDEX IF NOT EXISTS idx_durable_events_schema_sequence
    ON durable_events (tenant_scope, data_schema, stream_id, stream_sequence);
CREATE INDEX IF NOT EXISTS idx_durable_events_correlation
    ON durable_events (tenant_scope, correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS event_subscriptions (
    subscription_id               TEXT NOT NULL,
    subscription_version          INTEGER NOT NULL,
    tenant_id                     TEXT,
    tenant_scope                  TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    consumer_id                   TEXT NOT NULL,
    event_types                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_schemas                  JSONB NOT NULL DEFAULT '[]'::jsonb,
    start_policy                  TEXT NOT NULL,
    start_sequence                BIGINT,
    performs_external_effects     BOOLEAN NOT NULL DEFAULT FALSE,
    consumer_effect_id            TEXT,
    consumer_effect_scope         TEXT GENERATED ALWAYS AS (COALESCE(consumer_effect_id, '')) STORED,
    idempotency_strategy          TEXT,
    retry_max_attempts            INTEGER NOT NULL DEFAULT 5,
    retry_initial_delay_seconds   DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    retry_multiplier              DOUBLE PRECISION NOT NULL DEFAULT 2.0,
    retry_max_delay_seconds       DOUBLE PRECISION NOT NULL DEFAULT 60.0,
    retry_jitter_ratio            DOUBLE PRECISION NOT NULL DEFAULT 0.2,
    lease_duration_seconds        DOUBLE PRECISION NOT NULL DEFAULT 30.0,
    batch_size                    INTEGER NOT NULL DEFAULT 100,
    max_in_flight                 INTEGER NOT NULL DEFAULT 100,
    max_concurrency               INTEGER NOT NULL DEFAULT 1,
    pending_warning_threshold     BIGINT NOT NULL DEFAULT 10000,
    pending_hard_limit            BIGINT NOT NULL DEFAULT 100000,
    status                        TEXT NOT NULL DEFAULT 'active',
    supports_out_of_order_repair  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_event_subscriptions
        PRIMARY KEY (subscription_id, subscription_version),
    CONSTRAINT uq_event_subscriptions_tenant_scope
        UNIQUE (subscription_id, subscription_version, tenant_scope),
    CONSTRAINT uq_event_subscriptions_delivery_ref
        UNIQUE (
            subscription_id,
            subscription_version,
            tenant_scope,
            consumer_id,
            consumer_effect_scope
        ),
    CONSTRAINT ck_event_subscriptions_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_subscriptions_identity
        CHECK (
            btrim(subscription_id) <> ''
            AND btrim(consumer_id) <> ''
            AND (consumer_effect_id IS NULL OR btrim(consumer_effect_id) <> '')
        ),
    CONSTRAINT ck_event_subscriptions_version
        CHECK (subscription_version >= 1),
    CONSTRAINT ck_event_subscriptions_filters
        CHECK (jsonb_typeof(event_types) = 'array' AND jsonb_typeof(data_schemas) = 'array'),
    CONSTRAINT ck_event_subscriptions_start
        CHECK (
            (start_policy = 'at_sequence' AND start_sequence >= 1)
            OR (start_policy IN ('earliest', 'latest') AND start_sequence IS NULL)
        ),
    CONSTRAINT ck_event_subscriptions_effect_contract
        CHECK (
            (idempotency_strategy IS NULL OR consumer_effect_id IS NOT NULL)
            AND (
                NOT performs_external_effects
                OR (consumer_effect_id IS NOT NULL AND idempotency_strategy IS NOT NULL)
            )
        ),
    CONSTRAINT ck_event_subscriptions_idempotency_strategy
        CHECK (
            idempotency_strategy IS NULL
            OR idempotency_strategy IN (
                'inbox_transaction',
                'target_idempotency_key',
                'idempotent_overwrite'
            )
        ),
    CONSTRAINT ck_event_subscriptions_retry
        CHECK (
            retry_max_attempts BETWEEN 1 AND 5
            AND retry_initial_delay_seconds > 0
            AND retry_multiplier >= 1
            AND retry_max_delay_seconds >= retry_initial_delay_seconds
            AND retry_jitter_ratio >= 0
            AND retry_jitter_ratio < 1
        ),
    CONSTRAINT ck_event_subscriptions_lease
        CHECK (lease_duration_seconds BETWEEN 5 AND 300),
    CONSTRAINT ck_event_subscriptions_limits
        CHECK (
            batch_size >= 1
            AND max_in_flight >= batch_size
            AND max_concurrency BETWEEN 1 AND max_in_flight
            AND pending_warning_threshold >= 1
            AND pending_hard_limit > pending_warning_threshold
        ),
    CONSTRAINT ck_event_subscriptions_status
        CHECK (status IN ('active', 'paused', 'retired')),
    CONSTRAINT ck_event_subscriptions_time
        CHECK (updated_at >= created_at)
);

CREATE INDEX IF NOT EXISTS idx_event_subscriptions_tenant_status
    ON event_subscriptions (tenant_scope, status, subscription_id, subscription_version);
CREATE INDEX IF NOT EXISTS idx_event_subscriptions_event_types_gin
    ON event_subscriptions USING GIN (event_types);
CREATE INDEX IF NOT EXISTS idx_event_subscriptions_data_schemas_gin
    ON event_subscriptions USING GIN (data_schemas);

CREATE TABLE IF NOT EXISTS event_subscription_stream_states (
    tenant_id                 TEXT,
    tenant_scope              TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    subscription_id           TEXT NOT NULL,
    subscription_version      INTEGER NOT NULL,
    stream_id                 TEXT NOT NULL,
    start_sequence            BIGINT NOT NULL,
    registration_watermark    BIGINT NOT NULL,
    retirement_watermark      BIGINT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_event_subscription_stream_states
        PRIMARY KEY (tenant_scope, subscription_id, subscription_version, stream_id),
    CONSTRAINT fk_event_subscription_stream_states_subscription
        FOREIGN KEY (subscription_id, subscription_version, tenant_scope)
        REFERENCES event_subscriptions (
            subscription_id,
            subscription_version,
            tenant_scope
        )
        ON DELETE RESTRICT,
    CONSTRAINT fk_event_subscription_stream_states_stream
        FOREIGN KEY (tenant_scope, stream_id)
        REFERENCES event_stream_sequences (tenant_scope, stream_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_subscription_stream_states_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_subscription_stream_states_values
        CHECK (
            btrim(stream_id) <> ''
            AND start_sequence >= 1
            AND registration_watermark >= 0
            AND start_sequence <= registration_watermark + 1
            AND (
                retirement_watermark IS NULL
                OR retirement_watermark >= registration_watermark
            )
        ),
    CONSTRAINT ck_event_subscription_stream_states_time
        CHECK (updated_at >= created_at)
);

CREATE INDEX IF NOT EXISTS idx_event_subscription_stream_states_stream
    ON event_subscription_stream_states (
        tenant_scope,
        stream_id,
        subscription_id,
        subscription_version
    );
CREATE INDEX IF NOT EXISTS idx_event_subscription_stream_states_retirement
    ON event_subscription_stream_states (
        subscription_id,
        subscription_version,
        retirement_watermark
    );

CREATE TABLE IF NOT EXISTS event_deliveries (
    delivery_id            TEXT PRIMARY KEY,
    event_id               TEXT NOT NULL,
    tenant_id              TEXT,
    tenant_scope           TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    stream_id              TEXT NOT NULL,
    stream_sequence        BIGINT NOT NULL,
    subscription_id        TEXT NOT NULL,
    subscription_version   INTEGER NOT NULL,
    consumer_id            TEXT NOT NULL,
    consumer_effect_id     TEXT,
    consumer_effect_scope  TEXT GENERATED ALWAYS AS (COALESCE(consumer_effect_id, '')) STORED,
    delivery_generation    INTEGER NOT NULL DEFAULT 1,
    state                  TEXT NOT NULL DEFAULT 'pending',
    attempt_count          INTEGER NOT NULL DEFAULT 0,
    available_at           TIMESTAMPTZ,
    lease_owner            TEXT,
    lease_generation       BIGINT,
    lease_expires_at       TIMESTAMPTZ,
    first_failure_at       TIMESTAMPTZ,
    last_failure_at        TIMESTAMPTZ,
    reason_class           TEXT,
    redacted_diagnostic    TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_event_deliveries_identity
        UNIQUE (event_id, subscription_id, subscription_version, delivery_generation),
    CONSTRAINT uq_event_deliveries_dead_letter_ref
        UNIQUE (
            delivery_id,
            event_id,
            tenant_scope,
            stream_id,
            stream_sequence,
            subscription_id,
            subscription_version,
            consumer_id,
            consumer_effect_scope,
            delivery_generation
        ),
    CONSTRAINT uq_event_deliveries_inbox_ref
        UNIQUE (delivery_id, event_id, tenant_scope, consumer_effect_scope),
    CONSTRAINT fk_event_deliveries_event
        FOREIGN KEY (event_id, tenant_scope, stream_id, stream_sequence)
        REFERENCES durable_events (event_id, tenant_scope, stream_id, stream_sequence)
        ON DELETE RESTRICT,
    CONSTRAINT fk_event_deliveries_subscription
        FOREIGN KEY (
            subscription_id,
            subscription_version,
            tenant_scope,
            consumer_id,
            consumer_effect_scope
        )
        REFERENCES event_subscriptions (
            subscription_id,
            subscription_version,
            tenant_scope,
            consumer_id,
            consumer_effect_scope
        )
        ON DELETE RESTRICT,
    CONSTRAINT fk_event_deliveries_stream_state
        FOREIGN KEY (tenant_scope, subscription_id, subscription_version, stream_id)
        REFERENCES event_subscription_stream_states (
            tenant_scope,
            subscription_id,
            subscription_version,
            stream_id
        )
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_deliveries_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_deliveries_identity
        CHECK (
            btrim(delivery_id) <> ''
            AND btrim(event_id) <> ''
            AND btrim(stream_id) <> ''
            AND btrim(subscription_id) <> ''
            AND btrim(consumer_id) <> ''
            AND (consumer_effect_id IS NULL OR btrim(consumer_effect_id) <> '')
            AND stream_sequence >= 1
            AND subscription_version >= 1
            AND delivery_generation >= 1
        ),
    CONSTRAINT ck_event_deliveries_state
        CHECK (state IN ('pending', 'claimed', 'retry_wait', 'acked', 'dropped', 'dead_letter')),
    CONSTRAINT ck_event_deliveries_attempts
        CHECK (
            (state = 'pending' AND attempt_count = 0)
            OR (state <> 'pending' AND attempt_count >= 1)
        ),
    CONSTRAINT ck_event_deliveries_lease_atomic
        CHECK (
            (lease_owner IS NULL AND lease_generation IS NULL AND lease_expires_at IS NULL)
            OR (
                lease_owner IS NOT NULL
                AND btrim(lease_owner) <> ''
                AND lease_generation >= 1
                AND lease_expires_at IS NOT NULL
            )
        ),
    CONSTRAINT ck_event_deliveries_claimed_lease
        CHECK (
            state <> 'claimed'
            OR (lease_owner IS NOT NULL AND lease_generation IS NOT NULL AND lease_expires_at IS NOT NULL)
        ),
    CONSTRAINT ck_event_deliveries_non_claimed_lease
        CHECK (state = 'claimed' OR lease_owner IS NULL),
    CONSTRAINT ck_event_deliveries_failure_atomic
        CHECK (
            (first_failure_at IS NULL AND last_failure_at IS NULL)
            OR (
                first_failure_at IS NOT NULL
                AND last_failure_at IS NOT NULL
                AND last_failure_at >= first_failure_at
            )
        ),
    CONSTRAINT ck_event_deliveries_failure_details
        CHECK (
            state NOT IN ('retry_wait', 'dead_letter')
            OR (
                first_failure_at IS NOT NULL
                AND reason_class IS NOT NULL
                AND btrim(reason_class) <> ''
            )
        ),
    CONSTRAINT ck_event_deliveries_diagnostic
        CHECK (redacted_diagnostic IS NULL OR char_length(redacted_diagnostic) <= 2048),
    CONSTRAINT ck_event_deliveries_time
        CHECK (updated_at >= created_at)
);

CREATE INDEX IF NOT EXISTS idx_event_deliveries_claimable
    ON event_deliveries (
        subscription_id,
        subscription_version,
        state,
        available_at,
        tenant_scope,
        stream_id,
        stream_sequence
    )
    WHERE state IN ('pending', 'retry_wait');
CREATE INDEX IF NOT EXISTS idx_event_deliveries_lease_expiry
    ON event_deliveries (lease_expires_at, subscription_id, subscription_version)
    WHERE state = 'claimed';
CREATE INDEX IF NOT EXISTS idx_event_deliveries_stream
    ON event_deliveries (
        tenant_scope,
        subscription_id,
        subscription_version,
        stream_id,
        stream_sequence
    );
CREATE INDEX IF NOT EXISTS idx_event_deliveries_event
    ON event_deliveries (event_id, delivery_generation);

CREATE TABLE IF NOT EXISTS event_inbox (
    event_id             TEXT NOT NULL,
    consumer_effect_id   TEXT NOT NULL,
    tenant_id            TEXT,
    tenant_scope         TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    completed_at         TIMESTAMPTZ NOT NULL,
    delivery_id          TEXT,
    result_checksum      TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_event_inbox
        PRIMARY KEY (event_id, consumer_effect_id),
    CONSTRAINT fk_event_inbox_event
        FOREIGN KEY (event_id, tenant_scope)
        REFERENCES durable_events (event_id, tenant_scope)
        ON DELETE RESTRICT,
    CONSTRAINT fk_event_inbox_delivery
        FOREIGN KEY (delivery_id, event_id, tenant_scope, consumer_effect_id)
        REFERENCES event_deliveries (
            delivery_id,
            event_id,
            tenant_scope,
            consumer_effect_scope
        )
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_inbox_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_inbox_identity
        CHECK (btrim(event_id) <> '' AND btrim(consumer_effect_id) <> ''),
    CONSTRAINT ck_event_inbox_result_checksum
        CHECK (result_checksum IS NULL OR result_checksum ~ '^sha256:[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_event_inbox_delivery
    ON event_inbox (delivery_id)
    WHERE delivery_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_event_inbox_tenant_completed
    ON event_inbox (tenant_scope, completed_at, event_id);

CREATE TABLE IF NOT EXISTS event_consumer_checkpoints (
    tenant_id                              TEXT,
    tenant_scope                           TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    subscription_id                        TEXT NOT NULL,
    subscription_version                   INTEGER NOT NULL,
    stream_id                              TEXT NOT NULL,
    highest_contiguous_terminal_sequence   BIGINT,
    last_event_id                          TEXT,
    terminal_disposition                   TEXT,
    updated_at                             TIMESTAMPTZ NOT NULL,
    checksum                               TEXT NOT NULL,
    checkpoint_version                     INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT pk_event_consumer_checkpoints
        PRIMARY KEY (tenant_scope, subscription_id, subscription_version, stream_id),
    CONSTRAINT fk_event_consumer_checkpoints_stream_state
        FOREIGN KEY (tenant_scope, subscription_id, subscription_version, stream_id)
        REFERENCES event_subscription_stream_states (
            tenant_scope,
            subscription_id,
            subscription_version,
            stream_id
        )
        ON DELETE RESTRICT,
    CONSTRAINT fk_event_consumer_checkpoints_last_event
        FOREIGN KEY (
            last_event_id,
            tenant_scope,
            stream_id,
            highest_contiguous_terminal_sequence
        )
        REFERENCES durable_events (event_id, tenant_scope, stream_id, stream_sequence)
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_consumer_checkpoints_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_consumer_checkpoints_identity
        CHECK (
            btrim(subscription_id) <> ''
            AND subscription_version >= 1
            AND btrim(stream_id) <> ''
            AND checkpoint_version >= 1
        ),
    CONSTRAINT ck_event_consumer_checkpoints_frontier
        CHECK (
            (
                highest_contiguous_terminal_sequence IS NULL
                AND last_event_id IS NULL
                AND terminal_disposition IS NULL
            )
            OR (
                highest_contiguous_terminal_sequence >= 1
                AND last_event_id IS NOT NULL
                AND terminal_disposition IN ('acked', 'dropped', 'dead_letter')
            )
        ),
    CONSTRAINT ck_event_consumer_checkpoints_checksum
        CHECK (checksum ~ '^sha256:[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_event_consumer_checkpoints_subscription
    ON event_consumer_checkpoints (
        subscription_id,
        subscription_version,
        tenant_scope,
        stream_id
    );

CREATE TABLE IF NOT EXISTS event_dead_letters (
    dead_letter_id        TEXT PRIMARY KEY,
    delivery_id           TEXT NOT NULL,
    event_id              TEXT NOT NULL,
    tenant_id             TEXT,
    tenant_scope          TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    stream_id             TEXT NOT NULL,
    stream_sequence       BIGINT NOT NULL,
    subscription_id       TEXT NOT NULL,
    subscription_version  INTEGER NOT NULL,
    consumer_id           TEXT NOT NULL,
    consumer_effect_id    TEXT,
    consumer_effect_scope TEXT GENERATED ALWAYS AS (COALESCE(consumer_effect_id, '')) STORED,
    delivery_generation   INTEGER NOT NULL,
    attempt_count         INTEGER NOT NULL,
    first_failure_at      TIMESTAMPTZ NOT NULL,
    last_failure_at       TIMESTAMPTZ NOT NULL,
    reason_class          TEXT NOT NULL,
    redacted_diagnostic   TEXT,
    disposition           TEXT NOT NULL DEFAULT 'open',
    operator_id           TEXT,
    operator_reason       TEXT,
    updated_at            TIMESTAMPTZ,
    CONSTRAINT uq_event_dead_letters_delivery
        UNIQUE (delivery_id),
    CONSTRAINT fk_event_dead_letters_delivery
        FOREIGN KEY (
            delivery_id,
            event_id,
            tenant_scope,
            stream_id,
            stream_sequence,
            subscription_id,
            subscription_version,
            consumer_id,
            consumer_effect_scope,
            delivery_generation
        )
        REFERENCES event_deliveries (
            delivery_id,
            event_id,
            tenant_scope,
            stream_id,
            stream_sequence,
            subscription_id,
            subscription_version,
            consumer_id,
            consumer_effect_scope,
            delivery_generation
        )
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_dead_letters_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_dead_letters_identity
        CHECK (
            btrim(dead_letter_id) <> ''
            AND btrim(delivery_id) <> ''
            AND btrim(event_id) <> ''
            AND btrim(stream_id) <> ''
            AND btrim(subscription_id) <> ''
            AND btrim(consumer_id) <> ''
            AND stream_sequence >= 1
            AND subscription_version >= 1
            AND delivery_generation >= 1
            AND attempt_count >= 1
        ),
    CONSTRAINT ck_event_dead_letters_failure
        CHECK (
            btrim(reason_class) <> ''
            AND last_failure_at >= first_failure_at
            AND (redacted_diagnostic IS NULL OR char_length(redacted_diagnostic) <= 2048)
        ),
    CONSTRAINT ck_event_dead_letters_disposition
        CHECK (disposition IN ('open', 'requeued', 'resolved')),
    CONSTRAINT ck_event_dead_letters_operator
        CHECK (
            (
                disposition = 'open'
                AND operator_id IS NULL
                AND operator_reason IS NULL
                AND updated_at IS NULL
            )
            OR (
                disposition IN ('requeued', 'resolved')
                AND operator_id IS NOT NULL
                AND operator_reason IS NOT NULL
                AND updated_at IS NOT NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_event_dead_letters_open
    ON event_dead_letters (
        tenant_scope,
        subscription_id,
        subscription_version,
        last_failure_at,
        dead_letter_id
    )
    WHERE disposition = 'open';
CREATE INDEX IF NOT EXISTS idx_event_dead_letters_event
    ON event_dead_letters (event_id, consumer_id, delivery_generation);

CREATE TABLE IF NOT EXISTS event_quarantine (
    quarantine_id          TEXT PRIMARY KEY,
    tenant_id              TEXT,
    tenant_scope           TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    source                 TEXT NOT NULL,
    reason                 TEXT NOT NULL,
    envelope_schema        TEXT,
    event_type             TEXT,
    data_schema            TEXT,
    redacted_diagnostic    TEXT,
    disposition            TEXT NOT NULL DEFAULT 'pending',
    operator_id            TEXT,
    operator_reason        TEXT,
    created_at             TIMESTAMPTZ NOT NULL,
    updated_at             TIMESTAMPTZ,
    CONSTRAINT ck_event_quarantine_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_quarantine_identity
        CHECK (btrim(quarantine_id) <> '' AND btrim(source) <> ''),
    CONSTRAINT ck_event_quarantine_reason
        CHECK (reason IN (
            'unknown_envelope_schema',
            'unknown_data_schema',
            'schema_validation_failed',
            'missing_occurred_at',
            'invalid_occurred_at',
            'context_conflict',
            'identity_collision',
            'corrupt_record',
            'unsupported_legacy_mapping',
            'upcast_failed',
            'security_scope_ambiguous'
        )),
    CONSTRAINT ck_event_quarantine_diagnostic
        CHECK (redacted_diagnostic IS NULL OR char_length(redacted_diagnostic) <= 2048),
    CONSTRAINT ck_event_quarantine_disposition
        CHECK (disposition IN ('pending', 'released', 'rejected')),
    CONSTRAINT ck_event_quarantine_operator
        CHECK (
            (
                disposition = 'pending'
                AND operator_id IS NULL
                AND operator_reason IS NULL
                AND updated_at IS NULL
            )
            OR (
                disposition IN ('released', 'rejected')
                AND operator_id IS NOT NULL
                AND operator_reason IS NOT NULL
                AND updated_at IS NOT NULL
                AND updated_at >= created_at
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_event_quarantine_tenant_status
    ON event_quarantine (tenant_scope, disposition, reason, created_at, quarantine_id);
CREATE INDEX IF NOT EXISTS idx_event_quarantine_schema
    ON event_quarantine (event_type, data_schema)
    WHERE event_type IS NOT NULL OR data_schema IS NOT NULL;

CREATE TABLE IF NOT EXISTS event_replay_reports (
    replay_id             TEXT PRIMARY KEY,
    tenant_id             TEXT,
    tenant_scope          TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    mode                  TEXT NOT NULL,
    source_stream_id      TEXT NOT NULL,
    high_watermark        BIGINT NOT NULL,
    status                TEXT NOT NULL,
    from_sequence         BIGINT,
    to_sequence           BIGINT,
    checkpoint_ref        TEXT,
    versions              JSONB NOT NULL DEFAULT '[]'::jsonb,
    applied_upcasters     JSONB NOT NULL DEFAULT '[]'::jsonb,
    quarantine_refs       JSONB NOT NULL DEFAULT '[]'::jsonb,
    mismatch_sequence     BIGINT,
    reason_class          TEXT,
    result_checksum       TEXT,
    started_at            TIMESTAMPTZ NOT NULL,
    finished_at           TIMESTAMPTZ,
    operator_id           TEXT,
    operator_reason       TEXT,
    CONSTRAINT fk_event_replay_reports_stream
        FOREIGN KEY (tenant_scope, source_stream_id)
        REFERENCES event_stream_sequences (tenant_scope, stream_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_replay_reports_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_replay_reports_identity
        CHECK (btrim(replay_id) <> '' AND btrim(source_stream_id) <> ''),
    CONSTRAINT ck_event_replay_reports_mode
        CHECK (mode IN ('rebuild_state', 'verify_history', 'redeliver')),
    CONSTRAINT ck_event_replay_reports_status
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    CONSTRAINT ck_event_replay_reports_range
        CHECK (
            high_watermark >= 0
            AND (from_sequence IS NULL OR from_sequence BETWEEN 1 AND high_watermark)
            AND (to_sequence IS NULL OR to_sequence BETWEEN 1 AND high_watermark)
            AND (from_sequence IS NULL OR to_sequence IS NULL OR to_sequence >= from_sequence)
            AND (mismatch_sequence IS NULL OR mismatch_sequence BETWEEN 1 AND high_watermark)
        ),
    CONSTRAINT ck_event_replay_reports_json
        CHECK (
            jsonb_typeof(versions) = 'array'
            AND jsonb_typeof(applied_upcasters) = 'array'
            AND jsonb_typeof(quarantine_refs) = 'array'
        ),
    CONSTRAINT ck_event_replay_reports_checksum
        CHECK (result_checksum IS NULL OR result_checksum ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_event_replay_reports_terminal
        CHECK (
            (
                status IN ('pending', 'running')
                AND finished_at IS NULL
                AND reason_class IS NULL
                AND result_checksum IS NULL
                AND mismatch_sequence IS NULL
            )
            OR (
                status = 'succeeded'
                AND finished_at IS NOT NULL
                AND result_checksum IS NOT NULL
                AND reason_class IS NULL
                AND mismatch_sequence IS NULL
            )
            OR (
                status = 'failed'
                AND finished_at IS NOT NULL
                AND reason_class IS NOT NULL
                AND result_checksum IS NULL
            )
        ),
    CONSTRAINT ck_event_replay_reports_time
        CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT ck_event_replay_reports_operator
        CHECK (
            (operator_id IS NULL AND operator_reason IS NULL)
            OR (operator_id IS NOT NULL AND operator_reason IS NOT NULL)
        ),
    CONSTRAINT ck_event_replay_reports_redelivery_operator
        CHECK (mode <> 'redeliver' OR (operator_id IS NOT NULL AND operator_reason IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_event_replay_reports_stream
    ON event_replay_reports (tenant_scope, source_stream_id, started_at, replay_id);
CREATE INDEX IF NOT EXISTS idx_event_replay_reports_status
    ON event_replay_reports (tenant_scope, status, started_at, replay_id);
