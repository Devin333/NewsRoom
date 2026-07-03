## ADDED Requirements

### Requirement: Field embedding recall is a channel
Paper RAG field embedding recall SHALL be implemented as a reusable recall channel.

#### Scenario: Channel searches field vectors
- **WHEN** field embedding recall is requested for a paper, query, fields, filters, and limit
- **THEN** the channel returns deduplicated `FieldEmbeddingHit` records sorted by score
- **AND** field retrieval failures return an empty list without breaking retrieval

### Requirement: Field channel preserves field metadata
Field embedding channel SHALL preserve field embedding metadata when merging hits into chunks.

#### Scenario: Field hit is merged into chunk
- **WHEN** a field embedding hit references a chunk in the requested paper
- **THEN** the merged chunk includes `field_embedding_scores`, `field_embedding_score`, `best_embedding_field`, and `field_embedding_hits`

### Requirement: Field channel can produce chunk rankings
Field embedding channel SHALL convert field hits into ranked chunk candidates for hybrid fusion.

#### Scenario: Field hit ranking is requested
- **WHEN** field hits reference available chunks
- **THEN** the channel returns chunks sorted by field score descending
