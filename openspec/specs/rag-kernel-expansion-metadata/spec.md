# rag-kernel-expansion-metadata Specification

## Purpose
TBD - created by archiving change rag-kernel-expansion-metadata. Update Purpose after archive.
## Requirements
### Requirement: Kernel defines expansion provenance metadata
The RAG kernel SHALL provide a domain-neutral expansion metadata contract for describing why an evidence item was expanded from another item.

#### Scenario: Expansion metadata serializes standard keys
- **WHEN** an expansion is described with source id, reason, edge, and rank
- **THEN** the helper returns `expanded_from_chunk_id`, `expansion_reason`, `expansion_edge`, and `expansion_rank`
- **AND** caller-provided metadata can be merged into the same payload

### Requirement: Expansion metadata validates required provenance
The expansion metadata contract SHALL reject missing source id, reason, edge, or invalid rank values.

#### Scenario: Invalid expansion provenance is rejected
- **WHEN** source id, reason, or edge is blank
- **THEN** the contract raises a validation error
- **AND** a negative rank is rejected

### Requirement: Paper expansion metadata uses the kernel contract
Research Paper expansion SHALL use the kernel metadata helper while keeping Paper-specific expansion rules in Research.

#### Scenario: Paper expansion output keys remain compatible
- **WHEN** Research marks table, formula, parent, or visual reference expansions
- **THEN** the same expansion metadata keys remain available
- **AND** framework code does not import Paper models or Paper-specific expansion rules

