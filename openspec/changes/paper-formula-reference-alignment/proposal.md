## Why

Formula chunks currently bind to one primary parent paragraph, but later paragraphs that explicitly cite the same equation are not preserved as evidence relationships. This loses useful explanatory context for RAG when an equation is introduced once and discussed across multiple paragraphs.

## What Changes

- Detect deterministic formula references in paragraph text, including `Eq. (1)`, `Equation 1`, and Chinese `公式(1)` forms.
- Add `formula_references` metadata to paragraph chunks when they explicitly reference known equations.
- Add `referenced_by_chunks` metadata to formula chunks while keeping a single `parent_chunk_id` for the primary explanation paragraph.
- Preserve equation `source_locator` and `formula_parent_match_strategy`; references must not overwrite formula location.

## Capabilities

### New Capabilities
- `paper-formula-reference-alignment`: Defines formula parent binding and multi-paragraph formula reference metadata.

### Modified Capabilities
- `research-runtime`: Research paper chunking must expose traceable formula reference metadata for downstream RAG evidence expansion.

## Impact

- Affects `business/research/document/chunker.py` and formula chunker tests.
- Uses existing chunk metadata payloads; no PostgreSQL or Qdrant schema migration is required.
- No new external service or model dependency.
