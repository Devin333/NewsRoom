# rag-kernel-retrieval Specification

## Purpose
TBD - created by archiving change rag-kernel-context-retrieval. Update Purpose after archive.
## Requirements
### Requirement: Evidence scores are fused from explicit components
The system SHALL provide a domain-neutral scoring helper that computes a final evidence score from explicit `RAGScoreBreakdown` components and configurable weights.

#### Scenario: Weighted final score is calculated
- **WHEN** evidence has child, parent, field, section, position, and rerank score components
- **THEN** the scoring helper returns a weighted final score
- **AND** the score output records the weights that contributed to the score

### Requirement: Missing score components remain absent
The retrieval scoring helper MUST NOT fabricate missing score components in the evidence breakdown.

#### Scenario: Sparse score breakdown remains sparse
- **WHEN** evidence lacks a parent relevance or rerank score component
- **THEN** the score breakdown keeps those components absent
- **AND** final score calculation only uses present components

### Requirement: Field scoring is deterministic and explainable
The system SHALL provide deterministic lexical field scoring for generic chunk fields and SHALL report the best matching field and per-field scores.

#### Scenario: Query matches caption field
- **WHEN** a query term overlaps with a chunk caption field
- **THEN** the field scoring helper records a positive caption score
- **AND** the best matching field is reported as caption

### Requirement: Evidence deduplication keeps highest scoring items
The system SHALL provide evidence deduplication that groups evidence by chunk id by default and keeps the highest scoring evidence for each group.

#### Scenario: Duplicate chunk evidence is deduped
- **WHEN** two evidence items refer to the same chunk id
- **THEN** the deduplication helper keeps only the higher scoring item
- **AND** unique chunk evidence remains in the output

