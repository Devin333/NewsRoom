## Context

The evaluator is not an ML subsystem. It should be deterministic, lightweight, and usable by tests and future business dashboards.

## Design

- Dataclass models describe ranking cases and evaluation results.
- Ranking metrics implement precision@k, recall@k, MRR, and NDCG.
- Path metrics inspect cross-board path completeness, evidence precision, and contradiction blocking.
- Memory metrics compare memory hit and score movement.
- `BusinessRunEvaluator` evaluates final runs, board rankings, and cross-board paths.

## Constraints

- No external services.
- Clamp metric scores to 0..1.
