## ADDED Requirements

### Requirement: Claim index recall is a channel
Paper RAG claim index recall SHALL be implemented as a reusable recall channel.

#### Scenario: Channel searches claim index
- **WHEN** claim recall is requested for a paper, query, and limit
- **THEN** the channel returns claim search hits from `PaperClaimSearchPort`
- **AND** claim retrieval failures return an empty list without breaking retrieval

### Requirement: Claim channel preserves claim metadata
Claim index channel SHALL preserve claim metadata when merging claim hits into chunks.

#### Scenario: Claim hit is merged into chunk
- **WHEN** a claim hit references a chunk in the requested paper
- **THEN** the merged chunk includes `claim_index_hit`, `claim_index_score`, `claim_id`, and `claim_text`

### Requirement: Claim channel can produce chunk rankings
Claim index channel SHALL convert claim hits into ranked chunk candidates for hybrid fusion.

#### Scenario: Claim hit ranking is requested
- **WHEN** claim hits reference available chunks
- **THEN** the channel returns chunks sorted by claim score descending
