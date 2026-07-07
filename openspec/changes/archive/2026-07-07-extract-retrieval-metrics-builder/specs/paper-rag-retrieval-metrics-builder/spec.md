## ADDED Requirements

### Requirement: Retrieval metadata is assembled by a dedicated builder
Paper RAG retrieval SHALL assemble result metadata through a dedicated metrics builder while preserving existing metadata keys and trace fields.

#### Scenario: Metrics builder preserves policy and trace fields
- **WHEN** retrieval completes through the pipeline
- **THEN** result metadata includes `retrieval_policy`, `retrieval_policy_config_hash`, `retrieval_trace`, and `retrieval_degradations`

#### Scenario: Metrics builder preserves recall and context counts
- **WHEN** recall, rerank, and context expansion stages return their outputs
- **THEN** result metadata includes the existing recall counts, field hit counts, returned child/parent/reference counts, and context expansion counts

#### Scenario: Pipeline delegates metrics assembly
- **WHEN** `RetrievalPipeline.retrieve()` builds a `RetrievalResult`
- **THEN** metadata is produced by `RetrievalMetricsBuilder` rather than an inline metrics dictionary in the pipeline
