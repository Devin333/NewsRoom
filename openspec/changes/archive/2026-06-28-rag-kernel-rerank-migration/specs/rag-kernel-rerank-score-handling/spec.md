## ADDED Requirements

### Requirement: Kernel validates and normalizes reranker scores
The RAG kernel SHALL provide a domain-neutral reranker score value object that validates score count and clamps scores into the `0.0` to `1.0` range.

#### Scenario: Scores are normalized
- **WHEN** raw reranker scores include values outside the valid range
- **THEN** the resulting score set clamps them into the valid range
- **AND** scores can be mapped back to candidate ids

#### Scenario: Score count mismatch is rejected
- **WHEN** raw reranker scores do not match the expected candidate count
- **THEN** the helper returns no score set
- **AND** callers can fall back to deterministic or semantic scores

### Requirement: Kernel provides deterministic rerank sort keys
The RAG kernel SHALL provide a reusable sort key for reranked candidates.

#### Scenario: Candidates are sorted by rerank, priority, and fallback score
- **WHEN** candidates have rerank score, priority tuple, and fallback score
- **THEN** the sort key ranks higher rerank scores first
- **AND** ties use lower priority tuple first
- **AND** remaining ties use higher fallback score first

### Requirement: Paper reranker score handling uses kernel helpers
Research retrieval SHALL use the kernel rerank helpers for generic score handling while keeping Paper-specific rerank construction in Research.

#### Scenario: Paper reranking remains behaviorally compatible
- **WHEN** base, field, table-context, or parent-context reranking runs
- **THEN** score validation and normalization use the kernel helpers
- **AND** Paper-specific query construction, passage construction, policy gates, metadata names, and expansion behavior remain unchanged
- **AND** existing Paper retrieval tests still pass
