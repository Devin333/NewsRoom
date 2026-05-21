## ADDED Requirements

### Requirement: Business Evaluation Metrics
The business layer SHALL provide deterministic ranking, path, memory, and quality metrics.

#### Scenario: Ranking metrics are deterministic
- **WHEN** expected and actual ranked IDs are evaluated
- **THEN** precision, recall, MRR, and NDCG return stable scores

### Requirement: Final Run Evaluator
The business layer SHALL evaluate final run and board outputs into evaluation results.

#### Scenario: Final run evaluation returns results
- **WHEN** a final business run is evaluated
- **THEN** evaluation results include metric name, score, pass status, and details
