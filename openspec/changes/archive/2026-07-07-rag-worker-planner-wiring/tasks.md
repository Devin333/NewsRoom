## 1. Framework Planner Wiring

- [x] 1.1 Extend `RAGPlanner`, `DeterministicRAGPlanner`, and `WorkerRAGPlanner` with `executed_queries` compatibility.
- [x] 1.2 Add `WorkerRAGPlanner.min_round_index` deterministic fallback behavior.
- [x] 1.3 Pass executed query history from `BoundedRAGSessionController` into planner calls.

## 2. Research Adapter And Session

- [x] 2.1 Add `ResearchRAGPlanWorker` adapter for `ResearchCandidateWorkerPort`.
- [x] 2.2 Wire optional plan worker through `PaperRAGSession`.
- [x] 2.3 Expose optional plan worker injection through `build_paper_rag_session()`.

## 3. Tests

- [x] 3.1 Add framework planner tests for min round, worker request payload, fallback, and executed queries.
- [x] 3.2 Add Research adapter tests for successful and failed worker payloads.
- [x] 3.3 Add Paper session/factory tests proving default deterministic behavior and optional worker planner wiring.

## 4. Validation

- [x] 4.1 Run targeted framework and Research tests.
- [x] 4.2 Run compile and strict OpenSpec validation.
- [x] 4.3 Commit the completed T3 slice.
