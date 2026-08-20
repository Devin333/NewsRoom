CREATE TABLE IF NOT EXISTS graph_runs (
    run_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    status TEXT NOT NULL,
    profile TEXT NOT NULL,
    topic TEXT,
    artifact_dir TEXT,
    manifest_path TEXT,
    events_path TEXT,
    error JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    title TEXT,
    report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    report_markdown TEXT,
    quality_score DOUBLE PRECISION,
    citation_coverage_score DOUBLE PRECISION,
    manifest_path TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE reports
    ADD COLUMN IF NOT EXISTS citation_coverage_score DOUBLE PRECISION;

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
    graph_id TEXT,
    graph_version TEXT,
    graph_ref TEXT,
    graph_checksum TEXT,
    node_id TEXT,
    node_instance_id TEXT,
    graph_checkpoint_ref TEXT,
    activity_id TEXT,
    attempt INTEGER,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_artifact_index_run_created
    ON artifact_index(run_id, created_at, artifact_id);

CREATE INDEX IF NOT EXISTS idx_artifact_index_step
    ON artifact_index(run_id, step_id);

-- Existing installations may have created artifact_index before Graph lineage
-- became part of the contract. Add the columns before the Graph indexes below.
ALTER TABLE artifact_index
    ADD COLUMN IF NOT EXISTS graph_id TEXT,
    ADD COLUMN IF NOT EXISTS graph_version TEXT,
    ADD COLUMN IF NOT EXISTS graph_ref TEXT,
    ADD COLUMN IF NOT EXISTS graph_checksum TEXT,
    ADD COLUMN IF NOT EXISTS node_id TEXT,
    ADD COLUMN IF NOT EXISTS node_instance_id TEXT,
    ADD COLUMN IF NOT EXISTS graph_checkpoint_ref TEXT,
    ADD COLUMN IF NOT EXISTS activity_id TEXT,
    ADD COLUMN IF NOT EXISTS attempt INTEGER;

CREATE INDEX IF NOT EXISTS idx_artifact_index_graph
    ON artifact_index(run_id, graph_id, graph_version, created_at, artifact_id);

CREATE INDEX IF NOT EXISTS idx_artifact_index_node_instance
    ON artifact_index(run_id, node_instance_id, created_at, artifact_id);

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
    graph_identity JSONB NOT NULL DEFAULT '{}'::jsonb,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lineage_refs_run
    ON lineage_refs(run_id);

CREATE INDEX IF NOT EXISTS idx_lineage_refs_target
    ON lineage_refs(run_id, target_type, target_id);

CREATE INDEX IF NOT EXISTS idx_lineage_refs_source
    ON lineage_refs(run_id, source_type, source_id);

ALTER TABLE lineage_refs
    ADD COLUMN IF NOT EXISTS graph_identity JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS source_items (
    source_item_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT,
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ,
    raw_artifact_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence_items (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_item_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION,
    category TEXT NOT NULL DEFAULT 'news',
    published_at TIMESTAMPTZ,
    lineage_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    text TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claims_run
    ON claims(run_id);

CREATE TABLE IF NOT EXISTS claim_supports (
    claim_support_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    run_id TEXT REFERENCES graph_runs(run_id) ON DELETE CASCADE,
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
    run_id TEXT REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    quality_score DOUBLE PRECISION,
    citation_coverage_score DOUBLE PRECISION,
    claim_support_score DOUBLE PRECISION,
    evidence_alignment_score DOUBLE PRECISION,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
    run_id TEXT REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    graph_id TEXT,
    agent_id TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_conversations_run
    ON agent_conversations(run_id);

CREATE INDEX IF NOT EXISTS idx_agent_conversations_agent
    ON agent_conversations(agent_id);

CREATE TABLE IF NOT EXISTS agent_conversation_messages (
    conversation_id TEXT NOT NULL REFERENCES agent_conversations(conversation_id) ON DELETE CASCADE,
    message_id TEXT NOT NULL,
    message_offset BIGINT NOT NULL,
    role TEXT NOT NULL,
    content JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    agent_id TEXT,
    run_id TEXT,
    redacted BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, message_id),
    UNIQUE (conversation_id, message_offset)
);

CREATE INDEX IF NOT EXISTS idx_agent_conversation_messages_conversation_offset
    ON agent_conversation_messages(conversation_id, message_offset);

CREATE INDEX IF NOT EXISTS idx_agent_conversation_messages_run
    ON agent_conversation_messages(run_id);

CREATE INDEX IF NOT EXISTS idx_agent_conversation_messages_agent
    ON agent_conversation_messages(agent_id);

CREATE TABLE IF NOT EXISTS agent_conversation_state (
    conversation_id TEXT PRIMARY KEY REFERENCES agent_conversations(conversation_id) ON DELETE CASCADE,
    summary TEXT,
    summary_updated_at TIMESTAMPTZ,
    cursor_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    compaction_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    iteration_checkpoint_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_conversation_state_updated
    ON agent_conversation_state(updated_at DESC);

CREATE TABLE IF NOT EXISTS tool_executions (
    tool_execution_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    graph_id TEXT,
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

CREATE INDEX IF NOT EXISTS idx_graph_runs_finished ON graph_runs(updated_at DESC);

-- A partially migrated installation may already have graph_runs without the
-- Graph identity columns. Add them before any Graph-specific index is built.
ALTER TABLE graph_runs
    ADD COLUMN IF NOT EXISTS graph_id TEXT,
    ADD COLUMN IF NOT EXISTS graph_version TEXT;

CREATE INDEX IF NOT EXISTS idx_graph_runs_graph_id ON graph_runs(graph_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_graph_runs_status ON graph_runs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_graph_runs_topic ON graph_runs(topic, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_graph_runs_metrics_gin ON graph_runs USING GIN(metrics);
CREATE INDEX IF NOT EXISTS idx_reports_run_id ON reports(run_id);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_json_gin ON reports USING GIN(report_json);
CREATE INDEX IF NOT EXISTS idx_reports_metadata_gin ON reports USING GIN(metadata_json);

ALTER TABLE graph_runs
    ADD COLUMN IF NOT EXISTS topic TEXT;

ALTER TABLE graph_runs
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE reports
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE source_items
    ADD COLUMN IF NOT EXISTS canonical_url TEXT;

ALTER TABLE source_items
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

ALTER TABLE source_items
    ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ;

ALTER TABLE source_items
    ADD COLUMN IF NOT EXISTS raw_artifact_id TEXT;

ALTER TABLE agent_conversations
    ADD COLUMN IF NOT EXISTS graph_id TEXT;

ALTER TABLE tool_executions
    ADD COLUMN IF NOT EXISTS graph_id TEXT;

ALTER TABLE source_items
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE source_items
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_source_items_run_id ON source_items(run_id);
CREATE INDEX IF NOT EXISTS idx_source_items_source_published ON source_items(source_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_items_published ON source_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_items_payload_gin ON source_items USING GIN(payload);
CREATE INDEX IF NOT EXISTS idx_source_items_metadata_gin ON source_items USING GIN(metadata_json);

ALTER TABLE evidence_items
    ADD COLUMN IF NOT EXISTS source_urls JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE evidence_items
    ADD COLUMN IF NOT EXISTS source_item_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE evidence_items
    ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';

ALTER TABLE evidence_items
    ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'news';

ALTER TABLE evidence_items
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

ALTER TABLE evidence_items
    ADD COLUMN IF NOT EXISTS lineage_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE evidence_items
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE evidence_items
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_evidence_items_run_id ON evidence_items(run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_items_category ON evidence_items(category);
CREATE INDEX IF NOT EXISTS idx_evidence_items_published ON evidence_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_items_source_urls_gin ON evidence_items USING GIN(source_urls);
CREATE INDEX IF NOT EXISTS idx_evidence_items_source_item_ids_gin ON evidence_items USING GIN(source_item_ids);
CREATE INDEX IF NOT EXISTS idx_evidence_items_lineage_gin ON evidence_items USING GIN(lineage_json);
CREATE INDEX IF NOT EXISTS idx_evidence_items_metadata_gin ON evidence_items USING GIN(metadata_json);

ALTER TABLE claims
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_payload_gin ON claims USING GIN(payload);

ALTER TABLE quality_results
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
