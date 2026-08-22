-- One-way generic Artifact index cutover. Rows with complete Graph lineage or
-- no Graph lineage are assigned an explicit live scope. Partial legacy rows
-- remain unscoped and therefore fail closed in the active reader.
ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS scope_kind TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS artifact_identity_key TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS graph_id TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS graph_version TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS graph_ref TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS graph_checksum TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS node_id TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS node_instance_id TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS graph_checkpoint_ref TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS activity_id TEXT;

ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS attempt INTEGER;

UPDATE artifact_index
SET
    scope_kind = 'graph',
    artifact_identity_key = concat(
        'graph', chr(31), run_id, chr(31), graph_id, chr(31), graph_version,
        chr(31), graph_ref, chr(31), graph_checksum, chr(31), node_id,
        chr(31), node_instance_id, chr(31), COALESCE(graph_checkpoint_ref, ''),
        chr(31), COALESCE(activity_id, ''), chr(31), COALESCE(attempt::text, ''),
        chr(31), artifact_id
    )
WHERE scope_kind IS NULL
  AND graph_id IS NOT NULL
  AND graph_version IS NOT NULL
  AND graph_ref IS NOT NULL
  AND graph_checksum IS NOT NULL
  AND node_id IS NOT NULL
  AND node_instance_id IS NOT NULL
  AND ((activity_id IS NULL AND attempt IS NULL)
       OR (activity_id IS NOT NULL AND attempt IS NOT NULL AND attempt > 0));

UPDATE artifact_index
SET
    scope_kind = 'standalone',
    artifact_identity_key = concat(
        'standalone', chr(31), run_id, chr(31), artifact_id
    )
WHERE scope_kind IS NULL
  AND graph_id IS NULL
  AND graph_version IS NULL
  AND graph_ref IS NULL
  AND graph_checksum IS NULL
  AND node_id IS NULL
  AND node_instance_id IS NULL
  AND graph_checkpoint_ref IS NULL
  AND activity_id IS NULL
  AND attempt IS NULL;

DO $$
DECLARE
    primary_key_definition TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid)
    INTO primary_key_definition
    FROM pg_constraint
    WHERE conrelid = 'artifact_index'::regclass
      AND conname = 'artifact_index_pkey'
      AND contype = 'p';

    IF primary_key_definition LIKE '%(run_id, artifact_id)%' THEN
        ALTER TABLE artifact_index DROP CONSTRAINT artifact_index_pkey;
    END IF;
END;
$$;

DROP INDEX IF EXISTS idx_artifact_index_step;
DROP INDEX IF EXISTS idx_artifact_index_graph;
DROP INDEX IF EXISTS idx_artifact_index_node_instance;

ALTER TABLE artifact_index
    DROP COLUMN IF EXISTS step_id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_index_identity
    ON artifact_index(artifact_identity_key)
    WHERE artifact_identity_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_artifact_index_scope_run
    ON artifact_index(scope_kind, run_id, created_at, artifact_id);

CREATE INDEX IF NOT EXISTS idx_artifact_index_graph
    ON artifact_index(
        run_id, graph_id, graph_version, graph_ref, graph_checksum,
        created_at, artifact_id
    )
    WHERE scope_kind = 'graph';

CREATE INDEX IF NOT EXISTS idx_artifact_index_node_instance
    ON artifact_index(
        run_id, graph_ref, graph_checksum, node_id, node_instance_id,
        activity_id, attempt, created_at, artifact_id
    )
    WHERE scope_kind = 'graph';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'artifact_index'::regclass
          AND conname = 'artifact_index_live_scope_required'
    ) THEN
        ALTER TABLE artifact_index
            ADD CONSTRAINT artifact_index_live_scope_required
            CHECK (scope_kind IS NOT NULL AND artifact_identity_key IS NOT NULL)
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'artifact_index'::regclass
          AND conname = 'artifact_index_scope_kind_check'
    ) THEN
        ALTER TABLE artifact_index
            ADD CONSTRAINT artifact_index_scope_kind_check
            CHECK (scope_kind IN ('graph', 'standalone'))
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'artifact_index'::regclass
          AND conname = 'artifact_index_scope_fields_check'
    ) THEN
        ALTER TABLE artifact_index
            ADD CONSTRAINT artifact_index_scope_fields_check
            CHECK (
                (scope_kind = 'standalone'
                    AND graph_id IS NULL AND graph_version IS NULL
                    AND graph_ref IS NULL AND graph_checksum IS NULL
                    AND node_id IS NULL AND node_instance_id IS NULL
                    AND graph_checkpoint_ref IS NULL
                    AND activity_id IS NULL AND attempt IS NULL)
                OR
                (scope_kind = 'graph'
                    AND graph_id IS NOT NULL AND graph_version IS NOT NULL
                    AND graph_ref IS NOT NULL AND graph_checksum IS NOT NULL
                    AND node_id IS NOT NULL AND node_instance_id IS NOT NULL
                    AND ((activity_id IS NULL AND attempt IS NULL)
                        OR (activity_id IS NOT NULL AND attempt IS NOT NULL
                            AND attempt > 0)))
            ) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'artifact_index'::regclass
          AND conname = 'artifact_index_graph_ref_check'
    ) THEN
        ALTER TABLE artifact_index
            ADD CONSTRAINT artifact_index_graph_ref_check
            CHECK (graph_ref IS NULL OR graph_ref = graph_id || '@' || graph_version)
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'artifact_index'::regclass
          AND conname = 'artifact_index_checksum_check'
    ) THEN
        ALTER TABLE artifact_index
            ADD CONSTRAINT artifact_index_checksum_check
            CHECK (
                graph_checksum IS NULL
                OR graph_checksum ~ '^sha256:[0-9a-f]{64}$'
            ) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'artifact_index'::regclass
          AND conname = 'artifact_index_identity_key_check'
    ) THEN
        ALTER TABLE artifact_index
            ADD CONSTRAINT artifact_index_identity_key_check
            CHECK (
                artifact_identity_key = CASE scope_kind
                    WHEN 'standalone' THEN concat(
                        'standalone', chr(31), run_id, chr(31), artifact_id
                    )
                    WHEN 'graph' THEN concat(
                        'graph', chr(31), run_id, chr(31), graph_id,
                        chr(31), graph_version, chr(31), graph_ref,
                        chr(31), graph_checksum, chr(31), node_id,
                        chr(31), node_instance_id, chr(31),
                        COALESCE(graph_checkpoint_ref, ''), chr(31),
                        COALESCE(activity_id, ''), chr(31),
                        COALESCE(attempt::text, ''), chr(31), artifact_id
                    )
                END
            ) NOT VALID;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION reject_artifact_index_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'artifact index records are immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_artifact_index_immutable ON artifact_index;
CREATE TRIGGER trg_artifact_index_immutable
BEFORE UPDATE ON artifact_index
FOR EACH ROW
EXECUTE FUNCTION reject_artifact_index_update();
