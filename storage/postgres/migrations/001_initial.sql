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
