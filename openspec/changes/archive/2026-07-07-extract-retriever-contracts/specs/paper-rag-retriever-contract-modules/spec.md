## ADDED Requirements

### Requirement: Retrieval contracts are owned by dedicated modules
Paper RAG retrieval SHALL define request, result, and policy contracts outside the retriever wiring entrypoint.

#### Scenario: Compatibility imports remain available
- **WHEN** callers import `RetrievalPolicy`, `RetrievalRequest`, or `RetrievalResult` from `business.research.rag.retrieval.paper_retriever`
- **THEN** the import still succeeds and resolves to the same classes exposed by the new contract modules

#### Scenario: Evidence candidate conversion is preserved
- **WHEN** `RetrievalResult.as_evidence_candidates()` is called after the move
- **THEN** it returns the same evidence candidate shape and metadata keys as before

#### Scenario: Retriever entrypoint is wiring-focused
- **WHEN** `paper_retriever.py` is inspected after the move
- **THEN** it contains the `ResearchRetriever` entrypoint and compatibility exports, while policy and DTO definitions live in their dedicated modules
