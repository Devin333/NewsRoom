## ADDED Requirements

### Requirement: Retrieval executes through an explicit pipeline entrypoint
Paper RAG retrieval SHALL execute end-to-end retrieval orchestration through a dedicated `RetrievalPipeline` while preserving the `ResearchRetriever.retrieve()` contract.

#### Scenario: Retriever delegates retrieval
- **WHEN** `ResearchRetriever.retrieve()` receives a `RetrievalRequest`
- **THEN** it returns the `RetrievalResult` produced by the configured `RetrievalPipeline`

#### Scenario: Pipeline preserves metadata
- **WHEN** retrieval completes through the pipeline
- **THEN** result metadata includes the existing policy, route, recall, rerank, context expansion, scoring, and trace fields

#### Scenario: Existing retrieval behavior remains stable
- **WHEN** existing retrieval tests run against `ResearchRetriever`
- **THEN** child, parent, reference, and metadata expectations remain compatible with the pre-pipeline behavior
