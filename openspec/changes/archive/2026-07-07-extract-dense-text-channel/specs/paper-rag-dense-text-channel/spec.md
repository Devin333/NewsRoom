## ADDED Requirements

### Requirement: Dense text recall is a channel
Paper RAG dense text recall SHALL be implemented as a reusable recall channel.

#### Scenario: Channel emits semantic text candidates
- **WHEN** dense text recall is requested for a paper, query, filters, and limit
- **THEN** the channel returns candidates from `ChunkStorePort.search_with_scores`
- **AND** each returned ranked hit includes `chunk_id`, `score`, `channel`, and metadata

### Requirement: Dense channel preserves hybrid failure behavior
Dense text recall SHALL support suppressed retrieval failures for hybrid recall.

#### Scenario: Hybrid dense search fails
- **WHEN** dense text recall raises during hybrid RRF candidate gathering
- **THEN** the channel can return an empty candidate list
- **AND** the caller can continue with other recall channels
