## ADDED Requirements

### Requirement: Kernel normalizes score weights
The RAG kernel SHALL provide a domain-neutral helper for normalizing score weights over a declared set of component keys.

#### Scenario: Positive weights are normalized
- **WHEN** score weights include positive, zero, negative, and unknown keys
- **THEN** only declared keys are returned
- **AND** negative values are clamped to zero
- **AND** positive declared values are normalized to sum to one

#### Scenario: No positive weight falls back
- **WHEN** declared weights have no positive values
- **THEN** the helper returns the caller-provided fallback weights

### Requirement: Kernel composes weighted component scores
The RAG kernel SHALL provide a domain-neutral helper for weighted component summation.

#### Scenario: Missing components are ignored
- **WHEN** a component score is missing or `None`
- **THEN** it contributes no score
- **AND** present components are multiplied by their configured weights and summed

### Requirement: Paper retriever uses kernel score-weight primitives
Research retrieval SHALL use kernel score-weight helpers for generic score math while keeping Paper-specific scoring policy in Research.

#### Scenario: Research child, parent, and field scores are composed
- **WHEN** `ResearchRetriever` computes field, child, or parent scores
- **THEN** the weighted sum is performed through `framework/rag/retrieval`
- **AND** Paper-specific field extraction, intent weights, graph scoring, section heading scoring, element label scoring, reranking, and expansion remain Research-owned

### Requirement: Score migration preserves Paper retrieval behavior
The migration SHALL preserve existing Paper retriever ordering and metadata for equivalent inputs.

#### Scenario: Existing retriever tests run
- **WHEN** Research retriever tests run after the migration
- **THEN** field score, child score, parent score, visual fusion, reranker, and expansion expectations still pass
