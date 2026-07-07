## 1. Policy and Controller

- [x] 1.1 Add `max_supplemental_rounds` to `RAGExecutionPolicy`.
- [x] 1.2 Gate supplemental repair with the independent generation policy budget.
- [x] 1.3 Stop charging supplemental repair against main `rounds` and `replans`.
- [x] 1.4 Emit stable supplemental skip reason codes.

## 2. Metrics

- [x] 2.1 Aggregate supplemental skip reason codes in `RAGSessionMetrics`.
- [x] 2.2 Include supplemental skip reasons in metrics serialization.

## 3. Tests and Validation

- [x] 3.1 Add a generation phase test proving supplemental repair runs when main replan budget is exhausted.
- [x] 3.2 Update exhaustion coverage to use `max_supplemental_rounds=0` and assert skip reason metrics.
- [x] 3.3 Run targeted generation, metrics, architecture, compile, and OpenSpec validation checks.
