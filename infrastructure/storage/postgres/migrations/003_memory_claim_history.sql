CREATE TABLE IF NOT EXISTS memory_claim_history (
    history_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    old_confidence DOUBLE PRECISION,
    new_confidence DOUBLE PRECISION,
    reason TEXT,
    evidence_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_memory_claim_history_claim
    ON memory_claim_history(claim_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_claim_history_evidence
    ON memory_claim_history(evidence_id);

ALTER TABLE memory_event_entities
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'mentioned';

ALTER TABLE memory_event_claims
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'supporting';

ALTER TABLE memory_event_evidence
    ADD COLUMN IF NOT EXISTS support_type TEXT NOT NULL DEFAULT 'supporting';

DROP INDEX IF EXISTS idx_memory_event_entities_role;
CREATE INDEX IF NOT EXISTS idx_memory_event_entities_role
    ON memory_event_entities(event_id, entity_id, role);

DROP INDEX IF EXISTS idx_memory_event_claims_role;
CREATE INDEX IF NOT EXISTS idx_memory_event_claims_role
    ON memory_event_claims(event_id, claim_id, role);

DROP INDEX IF EXISTS idx_memory_event_evidence_support_type;
CREATE INDEX IF NOT EXISTS idx_memory_event_evidence_support_type
    ON memory_event_evidence(event_id, evidence_id, support_type);

ALTER TABLE memory_event_entities
    DROP CONSTRAINT IF EXISTS memory_event_entities_pkey;
ALTER TABLE memory_event_entities
    ADD PRIMARY KEY (event_id, entity_id, role);

ALTER TABLE memory_event_claims
    DROP CONSTRAINT IF EXISTS memory_event_claims_pkey;
ALTER TABLE memory_event_claims
    ADD PRIMARY KEY (event_id, claim_id, role);

ALTER TABLE memory_event_evidence
    DROP CONSTRAINT IF EXISTS memory_event_evidence_pkey;
ALTER TABLE memory_event_evidence
    ADD PRIMARY KEY (event_id, evidence_id, support_type);
