## ADDED Requirements

### Requirement: Sparse lexical recall is a channel
Paper RAG sparse lexical recall SHALL be implemented as a reusable recall channel.

#### Scenario: Channel emits sparse candidates
- **WHEN** sparse lexical recall is requested for a paper and query
- **THEN** the channel returns matching candidates with sparse lexical metadata
- **AND** the candidates use the persisted BM25 index when available

### Requirement: Sparse channel fallback remains observable
Sparse lexical channel fallback SHALL record degradations when the persisted BM25 index is missing or unreadable.

#### Scenario: BM25 index is missing
- **WHEN** the sparse channel cannot find a persisted BM25 index
- **THEN** it falls back to `ChunkStorePort.list_chunks`
- **AND** it records `sparse_bm25_index_missing` in retrieval trace

### Requirement: Formula sparse fallback is preserved
Sparse lexical recall SHALL preserve formula sparse fallback for formula queries.

#### Scenario: Formula symbol is not returned by BM25
- **WHEN** BM25 does not return a formula chunk but formula sparse scoring matches it
- **THEN** the sparse channel still returns that formula chunk with formula sparse metadata
