-- Additive durable storage for deterministic replay checkpoints.
-- Replay checkpoints are mutable replay-owned progress slots.  They are kept
-- separate from immutable source events, replay reports, and consumer
-- contiguous-frontier checkpoints.

CREATE TABLE IF NOT EXISTS event_replay_checkpoints (
    checkpoint_id           TEXT PRIMARY KEY,
    tenant_id               TEXT,
    tenant_scope            TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
    mode                    TEXT NOT NULL,
    source_stream_id        TEXT NOT NULL,
    last_sequence           BIGINT NOT NULL,
    source_high_watermark   BIGINT NOT NULL,
    runtime_version         TEXT NOT NULL,
    schema_catalog_version  TEXT NOT NULL,
    reducer_id              TEXT,
    reducer_scope           TEXT GENERATED ALWAYS AS (COALESCE(reducer_id, '')) STORED,
    reducer_version         TEXT,
    parent_checkpoint_id    TEXT,
    parent_checkpoint_scope TEXT GENERATED ALWAYS AS (COALESCE(parent_checkpoint_id, '')) STORED,
    history_checksum        TEXT NOT NULL,
    checkpoint_checksum     TEXT NOT NULL,
    checkpoint_json         JSONB NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_event_replay_checkpoints_tenant_scope
        UNIQUE (checkpoint_id, tenant_scope),
    CONSTRAINT fk_event_replay_checkpoints_source
        FOREIGN KEY (tenant_scope, source_stream_id)
        REFERENCES event_stream_sequences (tenant_scope, stream_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_event_replay_checkpoints_tenant
        CHECK (tenant_id IS NULL OR btrim(tenant_id) <> ''),
    CONSTRAINT ck_event_replay_checkpoints_identity
        CHECK (
            btrim(checkpoint_id) <> ''
            AND btrim(source_stream_id) <> ''
            AND btrim(runtime_version) <> ''
            AND btrim(schema_catalog_version) <> ''
        ),
    CONSTRAINT ck_event_replay_checkpoints_mode
        CHECK (mode IN ('rebuild_state', 'verify_history')),
    CONSTRAINT ck_event_replay_checkpoints_sequence
        CHECK (last_sequence >= 0 AND source_high_watermark >= last_sequence),
    CONSTRAINT ck_event_replay_checkpoints_reducer
        CHECK (
            (
                mode = 'rebuild_state'
                AND reducer_id IS NOT NULL
                AND btrim(reducer_id) <> ''
                AND reducer_version IS NOT NULL
                AND btrim(reducer_version) <> ''
            )
            OR
            (
                mode = 'verify_history'
                AND reducer_id IS NULL
                AND reducer_version IS NULL
            )
        ),
    CONSTRAINT ck_event_replay_checkpoints_parent
        CHECK (
            parent_checkpoint_id IS NULL
            OR (
                btrim(parent_checkpoint_id) <> ''
                AND parent_checkpoint_id <> checkpoint_id
            )
        ),
    CONSTRAINT ck_event_replay_checkpoints_history_checksum
        CHECK (history_checksum ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_event_replay_checkpoints_checkpoint_checksum
        CHECK (checkpoint_checksum ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_event_replay_checkpoints_json
        CHECK (jsonb_typeof(checkpoint_json) = 'object'),
    CONSTRAINT ck_event_replay_checkpoints_time
        CHECK (updated_at >= created_at)
);

CREATE INDEX IF NOT EXISTS idx_event_replay_checkpoints_scope_stream
    ON event_replay_checkpoints (
        tenant_scope,
        source_stream_id,
        mode,
        last_sequence,
        checkpoint_id
    );

CREATE OR REPLACE FUNCTION enforce_event_replay_checkpoint_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF ROW(
        OLD.checkpoint_id,
        OLD.tenant_id,
        OLD.mode,
        OLD.source_stream_id,
        OLD.source_high_watermark,
        OLD.runtime_version,
        OLD.schema_catalog_version,
        OLD.reducer_id,
        COALESCE(OLD.reducer_version, ''),
        OLD.parent_checkpoint_id
    ) IS DISTINCT FROM ROW(
        NEW.checkpoint_id,
        NEW.tenant_id,
        NEW.mode,
        NEW.source_stream_id,
        NEW.source_high_watermark,
        NEW.runtime_version,
        NEW.schema_catalog_version,
        NEW.reducer_id,
        COALESCE(NEW.reducer_version, ''),
        NEW.parent_checkpoint_id
    ) THEN
        RAISE EXCEPTION 'replay checkpoint immutable identity changed'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.last_sequence < OLD.last_sequence THEN
        RAISE EXCEPTION 'replay checkpoint sequence regressed'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.last_sequence = OLD.last_sequence
       AND ROW(
            NEW.history_checksum,
            NEW.checkpoint_checksum,
            NEW.checkpoint_json
       ) IS DISTINCT FROM ROW(
            OLD.history_checksum,
            OLD.checkpoint_checksum,
            OLD.checkpoint_json
       ) THEN
        RAISE EXCEPTION 'equal replay checkpoint sequence is not exactly idempotent'
            USING ERRCODE = '23514';
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_event_replay_checkpoints_update'
          AND tgrelid = 'event_replay_checkpoints'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_event_replay_checkpoints_update
        BEFORE UPDATE ON event_replay_checkpoints
        FOR EACH ROW
        EXECUTE FUNCTION enforce_event_replay_checkpoint_update();
    END IF;
END;
$migration$;
