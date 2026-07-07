## ADDED Requirements

### Requirement: Production paper RAG wires deterministic relevance scoring
Production paper RAG sessions SHALL configure deterministic relevance scoring when
the paper reranker is enabled.

#### Scenario: Factory wires scorer from reranker
- **WHEN** `build_paper_rag_session(with_reranker=True)` builds a session
- **THEN** the session SHALL receive a `RelevanceScorerPort`
- **AND** that scorer SHALL use the same reranker instance configured for retrieval reranking

#### Scenario: Factory disables scorer with reranker disabled
- **WHEN** `build_paper_rag_session(with_reranker=False)` builds a session
- **THEN** the session SHALL not configure a relevance scorer

### Requirement: Research source policy declares relevance thresholds
Research RAG session specs SHALL include relevance thresholds for source verification.

#### Scenario: Default relevance threshold is present
- **WHEN** `ResearchRAGPolicyBuilder` builds a session spec
- **THEN** `source_policy.min_relevance` SHALL be present

#### Scenario: Evidence-type thresholds are present
- **WHEN** `ResearchRAGPolicyBuilder` builds a session spec
- **THEN** `source_policy.min_relevance_by_type` SHALL include relaxed thresholds for `table` and `formula`

### Requirement: Source verifier honors evidence-type relevance thresholds
Source verification SHALL apply evidence-type-specific relevance thresholds when configured.

#### Scenario: Type-specific threshold overrides default
- **WHEN** a candidate has an evidence type with a configured threshold
- **AND** a relevance score is below the default threshold but above the type-specific threshold
- **THEN** the candidate SHALL remain eligible for acceptance when quality and lineage gates pass
