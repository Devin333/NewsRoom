## ADDED Requirements

### Requirement: Visual recall is a channel
Paper RAG visual recall SHALL be implemented as a reusable recall channel.

#### Scenario: Channel searches visual vectors
- **WHEN** visual recall is requested for a paper, query, filters, and limit
- **THEN** the channel returns deduplicated visual hits sorted by score
- **AND** visual retrieval failures return an empty list without breaking retrieval

### Requirement: Visual channel preserves fusion metadata
Visual recall channel SHALL preserve text/image fusion metadata.

#### Scenario: Visual scores are fused with text candidates
- **WHEN** text candidates and visual hits are fused
- **THEN** returned chunks include `text_score`, `visual_score`, `fused_score`, `fusion_strategy`, and `visual_hit`

### Requirement: Visual channel can produce chunk rankings
Visual recall channel SHALL convert visual hits into ranked chunk candidates for hybrid fusion.

#### Scenario: Visual hit ranking is requested
- **WHEN** visual hits reference available chunks
- **THEN** the channel returns chunks sorted by visual score descending
