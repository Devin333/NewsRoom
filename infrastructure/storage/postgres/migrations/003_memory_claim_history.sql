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
