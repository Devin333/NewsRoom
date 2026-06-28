## ADDED Requirements

### Requirement: Optional lightweight reranker

Paper RAG live benchmark retrieval SHALL support an explicitly enabled lightweight reranker.

#### Scenario: Reranker switch

- **WHEN** live benchmark or evidence evaluation enables the lightweight reranker switch
- **THEN** the retriever SHALL receive a `RerankerPort` implementation for structured field reranking
- **AND** default behavior SHALL remain unchanged when the switch is disabled

### Requirement: Structured rerank passages

Paper RAG reranking SHALL score structured passages rather than raw body text only.

#### Scenario: Structured fields

- **WHEN** a candidate is passed to the field reranker
- **THEN** the passage SHALL include section title, chunk type, caption, equation, table rows, table columns, visual description, referenced text, and body when available

### Requirement: Rerank observability

Paper RAG reports SHALL expose reranker usage.

#### Scenario: Rerank distribution

- **WHEN** rerank scores are present in retrieved evidence
- **THEN** evidence and benchmark reports SHALL include a `rerank_distribution`
- **AND** answer samples SHALL retain score breakdowns that include rerank score components
