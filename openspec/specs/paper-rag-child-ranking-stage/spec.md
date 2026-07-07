# paper-rag-child-ranking-stage Specification

## Purpose
TBD - created by archiving change extract-child-ranking-stage. Update Purpose after archive.
## Requirements
### Requirement: Child candidates are ranked by a dedicated stage
Paper RAG retrieval SHALL rank recalled child candidates through a dedicated child ranking stage.

#### Scenario: Base reranker threshold preserves fallback
- **WHEN** the base reranker is enabled and all candidates fall below the threshold
- **THEN** child ranking keeps the top fallback candidate instead of returning an empty result

#### Scenario: Visual hits are fused with child scores
- **WHEN** visual hits are present for recalled candidates
- **THEN** child ranking applies the existing visual/text fusion and returns scored chunks with visual metadata

#### Scenario: Pipeline delegates child ranking
- **WHEN** `RetrievalPipeline.retrieve()` finishes candidate recall
- **THEN** it calls `ChildRankingStage` and uses its structured result for child selection and metrics
