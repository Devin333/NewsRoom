## ADDED Requirements

### Requirement: Table reference context expansion is delegated to an expander module
Paper RAG retrieval SHALL expand table chunks into reference context through a dedicated table context expander.

#### Scenario: Table nearby and body references expand
- **WHEN** a table chunk has nearby context or body references
- **THEN** the expander returns those chunks with the existing table expansion metadata

#### Scenario: Table result context expands for result questions
- **WHEN** a table query should include result context
- **THEN** the expander searches result paragraphs and returns qualifying result or conclusion chunks

### Requirement: Table context reranking is preserved
The table context expander MUST preserve existing reranker behavior for heuristic table result candidates.

#### Scenario: Reranker orders result context
- **WHEN** a reranker is configured and returns valid scores
- **THEN** table result context chunks are ordered by rerank score and carry rerank metadata

#### Scenario: Reranker fails safely
- **WHEN** table context reranking fails or returns malformed scores
- **THEN** the expander falls back to deterministic result-context ordering
