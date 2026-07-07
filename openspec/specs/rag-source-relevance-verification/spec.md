# rag-source-relevance-verification Specification

## Purpose
TBD - created by archiving change rag-relevance-verification. Update Purpose after archive.
## Requirements
### Requirement: Harness verifies source relevance when scorer is configured
Harness RAG SHALL support deterministic relevance verification for source evidence through an injected scorer port.

#### Scenario: Relevant evidence is accepted
- **WHEN** `SourceVerifier` is configured with a relevance scorer
- **AND** a candidate receives a relevance score greater than or equal to the configured threshold
- **THEN** the candidate SHALL remain eligible for acceptance when existing quality and lineage gates pass

#### Scenario: Low relevance evidence is rejected
- **WHEN** `SourceVerifier` is configured with a relevance scorer
- **AND** a candidate receives a relevance score below the configured threshold
- **THEN** the candidate SHALL be rejected
- **AND** the rejected candidate metadata SHALL include `rejection_reason` set to `low_relevance`
- **AND** the rejected candidate metadata SHALL include its relevance score and threshold

#### Scenario: No scorer preserves current behavior
- **WHEN** `SourceVerifier` is not configured with a relevance scorer
- **THEN** source verification SHALL use only the existing source quality, lineage, and conflict checks

### Requirement: RAG session reports rejection summaries
Bounded RAG sessions SHALL expose structured rejection summaries in gap reports.

#### Scenario: Gap report includes low relevance rejection counts
- **WHEN** a retrieval round rejects evidence with `rejection_reason` metadata
- **THEN** the session gap report SHALL include `rejection_summary`
- **AND** the summary SHALL include counts grouped by rejection reason
- **AND** the summary SHALL include evidence type counts for each reason
