# storage-memory-final-target-closure Specification

## Purpose
TBD - created by archiving change storage-memory-final-target-closure. Update Purpose after archive.
## Requirements
### Requirement: Storage persists source, evidence, claim, and quality records
The system SHALL persist first-class source item, evidence item, claim, and quality result records in both local JSON and PostgreSQL-backed repositories.

#### Scenario: Run result persistence writes evidence and claims
- **WHEN** a run output contains an evidence bundle and verified findings
- **THEN** the persistence adapter writes evidence records, claim records, and a quality result record for that run

### Requirement: Redis is owned as runtime state only
The system SHALL expose Redis runtime storage for queues, locks, cache, and short-term pointers without storing final reports or evidence as long-term truth.

#### Scenario: Runtime pointer expires
- **WHEN** a runtime pointer is saved with a TTL
- **THEN** the Redis adapter writes it with expiry semantics

### Requirement: Storage does not own orphan paper retrieval hybrid search
The system SHALL NOT expose the old storage-layer `HybridSearchService` as the Paper RAG hybrid retrieval implementation.

#### Scenario: Paper RAG uses retrieval pipeline channels
- **WHEN** Paper RAG needs hybrid retrieval
- **THEN** it uses `business.research.rag.retrieval` channels, fusion, and metrics rather than `infrastructure.storage.hybrid_search`
