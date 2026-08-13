## 1. Contract and Regression Fixtures

- [x] 1.1 Add policy reference/checksum mismatch tests for direct patch validation and `TaskPlanStageRunner.apply_patch`
- [x] 1.2 Add mixed external/task input and equivalent `task:`/`task://` reference tests
- [x] 1.3 Add initial and patched deep/shared DAG regression tests
- [x] 1.4 Add halt persistence failure and patched reduce/replay/recovery parity tests

## 2. Policy and Dataflow Integrity

- [x] 2.1 Persist `policy_checksum` in new `ValidatedTaskPlan` versions while preserving legacy replay checksums
- [x] 2.2 Enforce exact policy reference and checksum before any patch-side durable mutation
- [x] 2.3 Implement one canonical task reference parser and use it in validation, patch validation, and scheduling
- [x] 2.4 Enforce per-reference task dependency, policy allowlist, stage-context, and future-stage diagnostics

## 3. Bounded DAG and Replay

- [x] 3.1 Implement deterministic O(V+E) DAG analysis with real depth memoization and stable failure codes
- [x] 3.2 Reuse bounded DAG semantics for initial candidates, patched plans, and scheduler ordering
- [x] 3.3 Forward complete Plan history, patches, results, and terminal-event policy through `TaskPlanReplayReducer.reduce`
- [x] 3.4 Verify patched histories produce identical projections through reduce, replay, and recovery without live workers

## 4. Durable Failure Semantics

- [x] 4.1 Make `TASK_PLAN_HALTED` persistence mandatory before returning ordinary blocked/failed stage results
- [x] 4.2 Raise `task_plan_halt_persistence_failed` with bounded run/stage/version/reason diagnostic evidence when halt commit fails
- [x] 4.3 Verify halt persistence uncertainty prevents subsequent dispatch, aggregation, verification, and publication

## 5. Validation and Delivery

- [x] 5.1 Run focused TaskPlan and Harness/workflow recovery tests
- [x] 5.2 Run `python -m scripts.dev compile` and `python -m scripts.dev smoke`
- [x] 5.3 Run `openspec validate harness-taskplan-integrity-hardening --strict`
- [x] 5.4 Audit the scoped diff, update task status, and commit only this change's files
