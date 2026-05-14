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

CREATE INDEX IF NOT EXISTS idx_claims_run
    ON claims(run_id);

CREATE TABLE IF NOT EXISTS claim_supports (
    claim_support_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    support_type TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (claim_id, evidence_id, support_type)
);

CREATE INDEX IF NOT EXISTS idx_claim_supports_claim
    ON claim_supports(claim_id);

CREATE INDEX IF NOT EXISTS idx_claim_supports_evidence
    ON claim_supports(run_id, evidence_id);

CREATE TABLE IF NOT EXISTS quality_results (
    quality_result_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    quality_score DOUBLE PRECISION,
    citation_coverage_score DOUBLE PRECISION,
    claim_support_score DOUBLE PRECISION,
    evidence_alignment_score DOUBLE PRECISION,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quality_results_run
    ON quality_results(run_id);

CREATE TABLE IF NOT EXISTS memory_documents (
    document_id TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    source_type TEXT NOT NULL,
    run_id TEXT,
    report_id TEXT,
    evidence_id TEXT,
    source_item_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_documents_collection
    ON memory_documents(collection);

CREATE INDEX IF NOT EXISTS idx_memory_documents_run
    ON memory_documents(run_id);

CREATE TABLE IF NOT EXISTS agent_conversations (
    conversation_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    workflow_id TEXT,
    agent_id TEXT,
    step_id TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_conversations_run
    ON agent_conversations(run_id);

CREATE INDEX IF NOT EXISTS idx_agent_conversations_agent
    ON agent_conversations(agent_id);

CREATE TABLE IF NOT EXISTS tool_executions (
    tool_execution_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    workflow_id TEXT,
    step_id TEXT,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    latency_ms DOUBLE PRECISION,
    request JSONB NOT NULL DEFAULT '{}'::jsonb,
    response JSONB NOT NULL DEFAULT '{}'::jsonb,
    error JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tool_executions_run
    ON tool_executions(run_id);

CREATE INDEX IF NOT EXISTS idx_tool_executions_tool
    ON tool_executions(tool_name, status);

CREATE TABLE IF NOT EXISTS schema_versions (
    schema_name TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT PRIMARY KEY,
    source_name TEXT,
    url TEXT,
    status TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ,
    last_error JSONB,
    success_count_24h INTEGER NOT NULL DEFAULT 0,
    failure_count_24h INTEGER NOT NULL DEFAULT 0,
    avg_latency_ms_24h DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE source_health
    ADD COLUMN IF NOT EXISTS source_name TEXT;

ALTER TABLE source_health
    ADD COLUMN IF NOT EXISTS url TEXT;

CREATE INDEX IF NOT EXISTS idx_source_health_status
    ON source_health(status);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_finished ON workflow_runs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_run_id ON reports(run_id);
