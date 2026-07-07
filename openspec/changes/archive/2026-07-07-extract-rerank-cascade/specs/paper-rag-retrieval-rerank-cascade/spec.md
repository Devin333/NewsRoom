## ADDED Requirements

### Requirement: Candidate rerank scores come from a dedicated cascade
Paper RAG retrieval SHALL calculate base candidate rerank scores through a dedicated `RerankCascade`.

#### Scenario: Reranker unavailable
- **WHEN** no base reranker is configured or reranking is disabled for the intent
- **THEN** the cascade returns the original semantic scores for each candidate

#### Scenario: Reranker returns valid scores
- **WHEN** a base reranker is configured and returns one score per candidate
- **THEN** the cascade returns those normalized scores in candidate order

#### Scenario: Reranker fails safely
- **WHEN** a base reranker raises an error or returns a malformed score count
- **THEN** the cascade falls back to the original semantic scores

### Requirement: Field rerank scores come from the cascade
Paper RAG retrieval SHALL calculate structured field rerank scores through the same rerank cascade.

#### Scenario: Field reranker unavailable
- **WHEN** no field reranker is configured or field reranking is disabled for the intent
- **THEN** the cascade returns an empty field rerank score map

#### Scenario: Field reranker returns valid scores
- **WHEN** a field reranker returns one score per chunk
- **THEN** the cascade returns a map from chunk id to normalized rerank score
