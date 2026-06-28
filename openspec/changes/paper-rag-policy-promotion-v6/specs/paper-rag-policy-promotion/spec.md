## ADDED Requirements

### Requirement: Blind semantic retrieval policy

Paper RAG SHALL expose an explicit blind semantic retrieval policy without changing default retrieval behavior.

#### Scenario: Explicit policy selection

- **WHEN** `paper_blind_semantic_rag_v1` is selected through CLI config or environment
- **THEN** the retriever SHALL use a named policy with blind semantic score weights and rerank intent scope
- **AND** selecting no policy SHALL preserve the default retrieval policy

### Requirement: Policy-bound lightweight reranker

The blind semantic retrieval policy SHALL activate the deterministic lightweight field reranker in benchmark live retrieval.

#### Scenario: Policy activates reranker

- **WHEN** live benchmark or evidence evaluation uses `paper_blind_semantic_rag_v1`
- **THEN** the retriever SHALL receive the lightweight field reranker
- **AND** report metadata SHALL show lightweight reranker enabled

### Requirement: Promotion checklist artifacts

Benchmark suite output SHALL include a deterministic policy promotion checklist.

#### Scenario: Checklist output

- **WHEN** the benchmark suite writes its report
- **THEN** it SHALL include `policy_promotion_checklist` in the suite JSON
- **AND** it SHALL write `policy_promotion_checklist.json` and `policy_promotion_checklist.md`

### Requirement: Promotion gate checks

The promotion checklist SHALL evaluate report completeness and PRD threshold metrics.

#### Scenario: Gate evaluation

- **WHEN** benchmark results are available
- **THEN** the checklist SHALL check question profile, retrieval policy, train/dev/test split, gold audit, ambiguity audit, route distribution, field embedding distribution, rerank distribution, by-qa-type retrieval metrics, answer success, and failure reasons
- **AND** it SHALL mark the policy as not ready when answer evaluation is missing or a threshold fails
