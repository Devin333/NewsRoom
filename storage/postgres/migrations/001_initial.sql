CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    status TEXT NOT NULL,
    profile TEXT NOT NULL,
    artifact_dir TEXT,
    manifest_path TEXT,
    events_path TEXT,
    error JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    title TEXT,
    report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    report_markdown TEXT,
    quality_score DOUBLE PRECISION,
    citation_coverage_score DOUBLE PRECISION,
    manifest_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE reports
    ADD COLUMN IF NOT EXISTS citation_coverage_score DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS workflow_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_offset BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    workflow_id TEXT,
    step_id TEXT,
    task_id TEXT,
    agent_id TEXT,
    tool_call_id TEXT,
    request_id TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    trace_id TEXT,
    redacted BOOLEAN NOT NULL DEFAULT TRUE,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, event_offset)
);

CREATE INDEX IF NOT EXISTS idx_workflow_events_run_offset
    ON workflow_events(run_id, event_offset);

CREATE INDEX IF NOT EXISTS idx_workflow_events_step
    ON workflow_events(run_id, step_id);

CREATE TABLE IF NOT EXISTS artifact_index (
    artifact_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT,
    checksum TEXT,
    redacted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_artifact_index_run_created
    ON artifact_index(run_id, created_at, artifact_id);

CREATE INDEX IF NOT EXISTS idx_artifact_index_step
    ON artifact_index(run_id, step_id);

CREATE TABLE IF NOT EXISTS lineage_refs (
    lineage_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lineage_refs_run
    ON lineage_refs(run_id);

CREATE INDEX IF NOT EXISTS idx_lineage_refs_target
    ON lineage_refs(run_id, target_type, target_id);

CREATE INDEX IF NOT EXISTS idx_lineage_refs_source
    ON lineage_refs(run_id, source_type, source_id);

CREATE TABLE IF NOT EXISTS source_items (
    source_item_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence_items (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    text TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS report_sections (
    section_id TEXT PRIMARY KEY,
    report_id TEXT REFERENCES reports(report_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_finished ON workflow_runs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_run_id ON reports(run_id);
