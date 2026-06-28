## ADDED Requirements

### Requirement: Kernel builds stable RAG ids
The RAG kernel SHALL provide a domain-neutral stable id helper for RAG artifacts.

#### Scenario: Equivalent parts produce the same id
- **WHEN** callers pass equivalent id parts that differ only by case or surrounding whitespace
- **THEN** the generated stable id is the same
- **AND** the prefix is normalized

### Requirement: Kernel builds chunk semantic keys
The RAG kernel SHALL provide a chunk semantic-key helper based on document id, chunk type, normalized section title, source locator, and normalized content hash.

#### Scenario: Semantic key exposes parts
- **WHEN** a chunk semantic key is built
- **THEN** the result includes the stable key
- **AND** the normalized content hash
- **AND** the explicit key parts used to build it

### Requirement: Paper chunk ids use kernel stable-id helpers
Research chunking SHALL use kernel id helpers for generic id and semantic-key construction while keeping Paper manifest behavior in Research.

#### Scenario: Manifest id reuse is preserved
- **WHEN** a paper is re-parsed and paragraph indexes shift
- **THEN** Research still uses the chunk manifest to reuse the previous chunk id for the same semantic key
- **AND** Paper-specific manifest storage, source locator selection, and span remapping remain Research-owned
