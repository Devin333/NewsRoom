# paper-rag-sparse-bm25-index Specification

## Purpose
TBD - created by archiving change sparse-bm25-index. Update Purpose after archive.
## Requirements
### Requirement: Sparse recall uses a paper-scoped BM25 index
Paper RAG sparse lexical recall SHALL use a paper-scoped BM25 index when one is available.

#### Scenario: BM25 index exists
- **WHEN** a paper BM25 index exists for the requested paper
- **THEN** sparse lexical recall ranks candidates from that index
- **AND** returned chunks keep sparse lexical hit metadata

### Requirement: Chunk ingestion writes the BM25 index
Paper chunk ingestion SHALL write or refresh the paper BM25 index after chunk ids are resolved.

#### Scenario: Chunk pipeline completes
- **WHEN** the chunk pipeline indexes chunks for a paper
- **THEN** a BM25 index artifact exists for that paper

### Requirement: Missing BM25 index falls back observably
Sparse lexical recall SHALL fall back to building an in-memory BM25 index from `list_chunks` when the persisted index is missing.

#### Scenario: BM25 index is missing
- **WHEN** sparse lexical recall is enabled and the index artifact does not exist
- **THEN** retrieval still completes using the chunk store inventory
- **AND** retrieval trace records a `sparse_bm25_index_missing` degradation
