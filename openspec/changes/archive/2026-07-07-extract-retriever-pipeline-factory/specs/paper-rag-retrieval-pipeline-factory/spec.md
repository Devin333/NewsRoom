## ADDED Requirements

### Requirement: Retrieval pipeline construction is owned by a factory
Paper RAG retrieval SHALL construct the composed retrieval pipeline through a dedicated factory instead of inline retriever wiring.

#### Scenario: Retriever constructor behavior is unchanged
- **WHEN** a caller constructs `ResearchRetriever` with a chunk store and optional retrieval adapters
- **THEN** the retriever builds a working pipeline and returns the same retrieval result shape

#### Scenario: Retriever entrypoint remains thin
- **WHEN** `paper_retriever.py` is inspected after the factory extraction
- **THEN** it remains a compatibility/public entrypoint and no longer owns channel, stage, and expander construction details

#### Scenario: Availability metadata is preserved
- **WHEN** optional adapters such as reranker, field index, visual store, or claim index are provided
- **THEN** the resulting retrieval metadata still reports their availability consistently with the pre-factory behavior
