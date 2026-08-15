-- Additive, append-only receipt ledger for Harness-authorized Reader Repair
-- memory commits. Header and members are written in the same transaction as
-- the referenced case/strategy versions.

CREATE TABLE IF NOT EXISTS reader_repair_memory_commits (
    idempotency_key    TEXT PRIMARY KEY,
    request_checksum   TEXT NOT NULL UNIQUE,
    request_id         TEXT NOT NULL,
    run_id             TEXT NOT NULL,
    terminal_effect_id TEXT NOT NULL,
    authorization_ref  TEXT NOT NULL,
    identity_scope_ref TEXT NOT NULL,
    subject_scope_ref  TEXT NOT NULL,
    namespace          TEXT NOT NULL,
    committed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_reader_repair_memory_commits_effect
        UNIQUE (run_id, terminal_effect_id),
    CONSTRAINT uq_reader_repair_memory_commits_namespace
        UNIQUE (idempotency_key, namespace),
    CONSTRAINT ck_reader_repair_memory_commits_identity
        CHECK (
            btrim(idempotency_key) <> ''
            AND btrim(request_id) <> ''
            AND btrim(run_id) <> ''
            AND btrim(terminal_effect_id) <> ''
            AND namespace = 'research.reader_repair'
        ),
    CONSTRAINT ck_reader_repair_memory_commits_checksums
        CHECK (
            request_checksum ~ '^sha256:[0-9a-f]{64}$'
            AND authorization_ref ~ '^sha256:[0-9a-f]{64}$'
            AND identity_scope_ref ~ '^sha256:[0-9a-f]{64}$'
            AND subject_scope_ref ~ '^sha256:[0-9a-f]{64}$'
        )
);

CREATE TABLE IF NOT EXISTS reader_repair_memory_commit_members (
    idempotency_key TEXT NOT NULL,
    namespace       TEXT NOT NULL,
    ordinal         INTEGER NOT NULL,
    object_type     TEXT NOT NULL CHECK (object_type IN ('case', 'strategy')),
    object_id       TEXT NOT NULL,
    version         INTEGER NOT NULL,
    CONSTRAINT pk_reader_repair_memory_commit_members
        PRIMARY KEY (idempotency_key, ordinal),
    CONSTRAINT uq_reader_repair_memory_commit_members_object
        UNIQUE (idempotency_key, object_type, object_id),
    CONSTRAINT fk_reader_repair_memory_commit_members_header
        FOREIGN KEY (idempotency_key, namespace)
        REFERENCES reader_repair_memory_commits (idempotency_key, namespace)
        ON DELETE RESTRICT,
    CONSTRAINT fk_reader_repair_memory_commit_members_version
        FOREIGN KEY (namespace, object_type, object_id, version)
        REFERENCES reader_repair_memory_versions (
            namespace,
            object_type,
            object_id,
            version
        )
        ON DELETE RESTRICT,
    CONSTRAINT ck_reader_repair_memory_commit_members_identity
        CHECK (
            btrim(object_id) <> ''
            AND version >= 1
            AND ordinal >= 0
            AND (
                (ordinal = 0 AND object_type = 'case')
                OR (ordinal >= 1 AND object_type = 'strategy')
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_reader_repair_memory_commits_run
    ON reader_repair_memory_commits (run_id, committed_at, idempotency_key);

CREATE INDEX IF NOT EXISTS idx_reader_repair_memory_commit_members_version
    ON reader_repair_memory_commit_members (
        namespace,
        object_type,
        object_id,
        version
    );

CREATE OR REPLACE FUNCTION enforce_reader_repair_memory_commit_members()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    case_count INTEGER;
    member_count INTEGER;
BEGIN
    SELECT
        COUNT(*) FILTER (WHERE object_type = 'case'),
        COUNT(*)
    INTO case_count, member_count
    FROM reader_repair_memory_commit_members
    WHERE idempotency_key = NEW.idempotency_key;

    IF case_count <> 1 OR member_count < 1 THEN
        RAISE EXCEPTION 'reader repair memory commit requires exactly one case member'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION reject_reader_repair_memory_commit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'reader repair memory commit receipts are append-only'
        USING ERRCODE = '23514';
END;
$$;

CREATE OR REPLACE FUNCTION reject_reader_repair_memory_version_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'reader repair memory versions are append-only'
        USING ERRCODE = '23514';
END;
$$;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_reader_repair_memory_commit_members_complete'
          AND tgrelid = 'reader_repair_memory_commits'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE CONSTRAINT TRIGGER trg_reader_repair_memory_commit_members_complete
        AFTER INSERT ON reader_repair_memory_commits
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION enforce_reader_repair_memory_commit_members();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_reader_repair_memory_commits_immutable'
          AND tgrelid = 'reader_repair_memory_commits'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_reader_repair_memory_commits_immutable
        BEFORE UPDATE OR DELETE ON reader_repair_memory_commits
        FOR EACH ROW
        EXECUTE FUNCTION reject_reader_repair_memory_commit_mutation();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_reader_repair_memory_commit_members_immutable'
          AND tgrelid = 'reader_repair_memory_commit_members'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_reader_repair_memory_commit_members_immutable
        BEFORE UPDATE OR DELETE ON reader_repair_memory_commit_members
        FOR EACH ROW
        EXECUTE FUNCTION reject_reader_repair_memory_commit_mutation();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_reader_repair_memory_versions_immutable'
          AND tgrelid = 'reader_repair_memory_versions'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_reader_repair_memory_versions_immutable
        BEFORE UPDATE OR DELETE ON reader_repair_memory_versions
        FOR EACH ROW
        EXECUTE FUNCTION reject_reader_repair_memory_version_mutation();
    END IF;
END;
$migration$;
