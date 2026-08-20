CREATE TABLE IF NOT EXISTS memory_entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    importance_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    trend_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    external_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_entities_type
    ON memory_entities(entity_type);

CREATE INDEX IF NOT EXISTS idx_memory_entities_name
    ON memory_entities(canonical_name);

CREATE TABLE IF NOT EXISTS memory_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_time TIMESTAMPTZ,
    detected_at TIMESTAMPTZ NOT NULL,
    topic TEXT,
    impact_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    novelty_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_events_run
    ON memory_events(run_id);

CREATE INDEX IF NOT EXISTS idx_memory_events_topic
    ON memory_events(topic);

CREATE TABLE IF NOT EXISTS memory_event_entities (
    event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, entity_id)
);

CREATE TABLE IF NOT EXISTS memory_event_claims (
    event_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, claim_id)
);

CREATE TABLE IF NOT EXISTS memory_event_evidence (
    event_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS memory_decisions (
    decision_id TEXT PRIMARY KEY,
    decision_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    run_id TEXT NOT NULL,
    graph_id TEXT,
    graph_version TEXT,
    graph_ref TEXT,
    graph_checksum TEXT,
    agent_id TEXT,
    input_features JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_decisions_run
    ON memory_decisions(run_id);

ALTER TABLE memory_decisions
    ADD COLUMN IF NOT EXISTS graph_id TEXT,
    ADD COLUMN IF NOT EXISTS graph_version TEXT,
    ADD COLUMN IF NOT EXISTS graph_ref TEXT,
    ADD COLUMN IF NOT EXISTS graph_checksum TEXT;

CREATE INDEX IF NOT EXISTS idx_memory_decisions_target
    ON memory_decisions(target_type, target_id);

CREATE TABLE IF NOT EXISTS memory_preferences (
    preference_id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    preference_type TEXT NOT NULL,
    content TEXT NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_memory_preferences_owner
    ON memory_preferences(owner_type, owner_id);
