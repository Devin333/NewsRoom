## ADDED Requirements

### Requirement: Retrieval reports expose multiple top-k cuts
Retrieval evaluation reports SHALL expose candidate-aware top-k metrics for at least `k=3`, `k=5`, and `k=10` when the evaluator is configured with those cutoffs.

#### Scenario: Top-k cuts are present in report metrics
- **WHEN** retrieval evaluation is run with `ks=(1, 3, 5, 10)`
- **THEN** Hit@K, equivalent Hit@K, evidence coverage@K, source locator coverage@K, and nDCG@K are available for `k=3`, `k=5`, and `k=10`
- **AND** downstream Paper RAG reports can read those values without recalculating metrics
