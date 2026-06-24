## ADDED Requirements

### Requirement: Child Retrieval Computes Field Scores
Research retrieval SHALL compute field-level relevance for child retrieval candidates.

#### Scenario: Candidate contains field text
- **WHEN** a child candidate has section title, abstract text, caption text, equation text, or body text
- **THEN** retrieval MUST compute corresponding field scores
- **AND** it MUST compute a weighted `field_score`

#### Scenario: Candidate lacks field text
- **WHEN** a candidate lacks one or more fields
- **THEN** missing field scores MUST be `0.0`
- **AND** semantic ranking MUST remain usable

### Requirement: Field Score Influences Child Ranking
Research retrieval SHALL blend field score with semantic score and position score.

#### Scenario: Field score is enabled
- **WHEN** child candidates are ranked
- **THEN** retrieval MUST compute `child_final_score`
- **AND** it MUST sort child candidates by `child_final_score` descending

#### Scenario: Semantic score is stronger than field boost
- **WHEN** field score is present
- **THEN** semantic score SHOULD remain the dominant ranking signal by default

### Requirement: Field Weights Depend On Query Intent
Research retrieval SHALL tune field weights by query intent.

#### Scenario: Figure or table query
- **WHEN** the route intent is `figure_query` or `table_query`
- **THEN** caption relevance SHOULD receive higher weight than abstract or equation relevance

#### Scenario: Formula query
- **WHEN** the route intent is `formula_query`
- **THEN** equation relevance SHOULD receive higher weight than caption or abstract relevance

#### Scenario: Contribution query
- **WHEN** the route intent is `contribution`
- **THEN** abstract and title relevance SHOULD receive higher weight

#### Scenario: Method query
- **WHEN** the route intent is `concept_method`
- **THEN** title and body relevance SHOULD contribute to field score

### Requirement: Field Scoring Is Observable
Research retrieval SHALL expose field score metadata for inspection and tuning.

#### Scenario: Scored chunk is returned as evidence
- **WHEN** retrieval returns a scored child chunk
- **THEN** evidence metadata MUST include field score breakdown and child final score metadata

#### Scenario: Retrieval scores child candidates
- **WHEN** retrieval computes field scores
- **THEN** retrieval metadata MUST include scoring enabled state, score weights, scored count, top score, and min score
