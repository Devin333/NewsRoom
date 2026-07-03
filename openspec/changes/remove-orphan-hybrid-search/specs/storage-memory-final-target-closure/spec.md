## REMOVED Requirements

### Requirement: Hybrid search combines keyword and semantic recall
The system SHALL expose a storage-layer hybrid search that can combine report keyword matches and vector memory matches into a unified SearchResult list.

#### Scenario: Keyword and vector results are merged
- **WHEN** reports and vector documents match a query
- **THEN** hybrid search returns scored results with keyword and semantic score fields

## ADDED Requirements

### Requirement: Storage does not own orphan paper retrieval hybrid search
The system SHALL NOT expose the old storage-layer `HybridSearchService` as the Paper RAG hybrid retrieval implementation.

#### Scenario: Paper RAG uses retrieval pipeline channels
- **WHEN** Paper RAG needs hybrid retrieval
- **THEN** it uses `business.research.rag.retrieval` channels, fusion, and metrics rather than `infrastructure.storage.hybrid_search`
