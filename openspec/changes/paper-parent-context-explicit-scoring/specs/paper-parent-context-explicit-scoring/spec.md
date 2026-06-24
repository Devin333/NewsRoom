## ADDED Requirements

### Requirement: Parent Context Has Explainable Final Scores
Research retrieval SHALL compute an explicit final score for parent context candidates.

#### Scenario: Parent candidate is scored
- **WHEN** a child chunk expands to a parent chunk
- **THEN** retrieval MUST compute `parent_final_score`
- **AND** it MUST include child relevance, parent relevance, heading relevance, and position score metadata

#### Scenario: Parent candidates are sorted
- **WHEN** multiple parent candidates exist
- **THEN** retrieval MUST sort them by `parent_final_score` descending
- **AND** it MUST use child rank as a deterministic tie-break

### Requirement: Parent Score Uses Intent-Specific Weights
Research retrieval SHALL tune parent score composition by query intent.

#### Scenario: Method-oriented query
- **WHEN** the query intent is `concept_method` or `contribution`
- **THEN** method-like section headings and roles SHOULD contribute more than they do in the default weighting

#### Scenario: Result-oriented query
- **WHEN** the query intent is `numerical_result` or `comparison`
- **THEN** result, experiment, analysis, and conclusion headings SHOULD contribute to parent ranking

#### Scenario: Table or formula query
- **WHEN** the query intent is `table_query` or `formula_query`
- **THEN** parent ranking SHOULD keep child relevance dominant and use a tighter parent relevance/heading blend

### Requirement: Parent Scoring Works Without Reranker
Research retrieval SHALL remain deterministic and explainable when parent reranking is unavailable.

#### Scenario: No reranker is configured
- **WHEN** parent candidates exist and no reranker is configured
- **THEN** retrieval MUST still compute `parent_final_score`
- **AND** `parent_score_strategy` MUST indicate deterministic scoring

#### Scenario: Reranker fails
- **WHEN** parent reranker scoring fails or returns malformed output
- **THEN** retrieval MUST fall back to deterministic scoring
- **AND** returned parent chunks MUST still expose score breakdown metadata

### Requirement: Parent Scoring Is Observable
Research retrieval SHALL expose summary metrics for parent scoring.

#### Scenario: Parent candidates are scored
- **WHEN** retrieval scores parent candidates
- **THEN** retrieval metadata MUST include parent scoring enabled state, candidate count, score weights, top score, and min score
