CREATE TABLE IF NOT EXISTS reader_repair_memory_objects (
    namespace       TEXT NOT NULL,
    object_type     TEXT NOT NULL CHECK (object_type IN ('case', 'strategy')),
    object_id       TEXT NOT NULL,
    issue_type      TEXT NOT NULL,
    error_signature TEXT,
    successful      BOOLEAN,
    status          TEXT,
    memory_kind     TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    active_version  INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, object_type, object_id)
);

CREATE TABLE IF NOT EXISTS reader_repair_memory_versions (
    namespace   TEXT NOT NULL,
    object_type TEXT NOT NULL CHECK (object_type IN ('case', 'strategy')),
    object_id   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    operation   TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, object_type, object_id, version)
);

CREATE INDEX IF NOT EXISTS idx_reader_repair_memory_objects_issue
    ON reader_repair_memory_objects(namespace, object_type, issue_type);

CREATE INDEX IF NOT EXISTS idx_reader_repair_memory_objects_signature
    ON reader_repair_memory_objects(namespace, object_type, error_signature)
    WHERE error_signature IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_reader_repair_memory_objects_status
    ON reader_repair_memory_objects(namespace, object_type, status)
    WHERE status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_reader_repair_memory_versions_object
    ON reader_repair_memory_versions(namespace, object_type, object_id, version);
