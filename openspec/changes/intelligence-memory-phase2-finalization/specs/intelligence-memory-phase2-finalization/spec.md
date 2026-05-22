## ADDED Requirements

### Requirement: Reindex exposes structured memory observability
The system SHALL expose structured memory counts, metadata, and full ingestion details in memory reindex results while preserving legacy reindex fields.

#### Scenario: Reindex result contains legacy and structured fields
- **WHEN** a completed run is reindexed into memory
- **THEN** the reindex payload includes `documents_indexed`, `collections`, `document_ids`, `counts`, `metadata`, and `ingestion`

### Requirement: Phase 2 ingestion behavior is covered end to end
The system SHALL verify that Phase 2 ingestion performs entity resolution, claim consolidation, claim history append, duplicate event handling, repository saves, and structured vector indexing.

#### Scenario: Duplicate and contradiction cases are observable
- **WHEN** related run outputs are ingested through the memory facade
- **THEN** ingestion metadata reports claim merge or contradiction actions, event duplicate handling, and structured document indexing

### Requirement: Report writer consumes historical memory context
The system SHALL build prompt-safe historical memory context from Recall v2 for report writing when a recall provider is configured.

#### Scenario: Writer receives recall context
- **WHEN** the report writer has memory context available for the topic
- **THEN** the draft metadata and LLM request include historical memory context while preserving fallback behavior when memory is unavailable

### Requirement: Ranking consumes structured memory explicitly
The system SHALL apply `MemoryFeatureComputer` ranking features only when an intelligence memory repository or feature computer is explicitly configured.

#### Scenario: Structured memory affects ranking when injected
- **WHEN** a ranking path receives an injected structured memory feature source
- **THEN** ranked output includes structured memory feature metadata and adjusted memory ranking features

### Requirement: Quality gate uses deterministic memory checks
The system SHALL run deterministic `QualityMemoryChecker` checks against available memory context and include the result in quality metadata.

#### Scenario: Critical memory issue can block quality
- **WHEN** memory context contains a critical quality issue
- **THEN** the quality gate records memory quality output and blocks or preserves existing blocking according to the issue severity

### Requirement: Memory factories and repositories remain protected by tests
The system SHALL test memory service factory sink selection and Postgres memory timeline, history, relation, decision, and preference queries.

#### Scenario: Factory and repository behavior is stable
- **WHEN** memory services or Postgres memory repositories are exercised by tests
- **THEN** they preserve sinkless protection, structured vector wiring, and timeline/history/relation query behavior
