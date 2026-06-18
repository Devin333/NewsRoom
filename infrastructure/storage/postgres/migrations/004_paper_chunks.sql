CREATE TABLE IF NOT EXISTS paper_chunks (
    chunk_id          TEXT PRIMARY KEY,
    paper_id          TEXT NOT NULL,
    chunk_type        TEXT NOT NULL,
    section_title     TEXT NOT NULL DEFAULT '',
    section_role      JSONB NOT NULL DEFAULT '[]'::jsonb,
    section_index     INTEGER NOT NULL DEFAULT 0,
    parse_source      TEXT NOT NULL,
    parent_chunk_id   TEXT REFERENCES paper_chunks(chunk_id) ON DELETE SET NULL,
    has_formula       BOOLEAN NOT NULL DEFAULT FALSE,
    has_figure        BOOLEAN NOT NULL DEFAULT FALSE,
    has_table         BOOLEAN NOT NULL DEFAULT FALSE,
    structure_detected       BOOLEAN NOT NULL DEFAULT TRUE,
    propositions_generated   BOOLEAN NOT NULL DEFAULT FALSE,
    proposition_quality      TEXT NOT NULL DEFAULT 'unknown',
    references_json   JSONB NOT NULL DEFAULT '[]'::jsonb,
    content           TEXT NOT NULL,
    payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper_id
    ON paper_chunks(paper_id);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_chunk_type
    ON paper_chunks(paper_id, chunk_type);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_parent
    ON paper_chunks(parent_chunk_id)
    WHERE parent_chunk_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_paper_chunks_payload_gin
    ON paper_chunks USING GIN(payload);
