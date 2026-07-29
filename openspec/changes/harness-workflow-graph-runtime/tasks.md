## 1. Baseline, Dependencies, and Golden Fixtures

- [ ] 1.1 Verify the required canonical event/replay contracts from `durable-event-runtime`, attempt termination/idempotency/fencing contracts from `framework-runtime-safety-hardening`, and side-effect decision/outcome contracts from `harness-side-effect-authority-closure`; record exact dependency versions and block unsafe fallbacks.
- [x] 1.2 Inventory all production and test callers of `HarnessWorkflowSpec`, `HarnessScheduler`, `HarnessState.current_step_id`, `HarnessRunStatus`, routing rules, checkpoints, replay, and run inspection, and classify each caller by migration phase.
- [x] 1.3 Capture canonical golden fixtures for the current linear Research workflow, conditional routes, retry/replan/repair, approval wait, side-effect publication, durable history, checkpoint, and final business result.
- [x] 1.4 Add baseline assertions that current Research Workers and Gates do not own workflow routing and that no new graph module imports `business`, `interfaces`, or `infrastructure`.
- [x] 1.5 Define the v2 graph/state/decision/event schema version registry and the bounded v1 reader/upcaster support window before implementation begins.

## 2. Graph DSL and Normalized Contracts

- [x] 2.1 Add immutable DSL contracts for `Sequence`, `Choice`, `ParallelAll`, `ParallelAny`, `BoundedLoop`, `Wait`, and explicit compensation bindings with canonical serialization tests.
- [x] 2.2 Add immutable normalized graph node, edge, control-node, branch, join, condition, Wait, loop, merge, and compensation reference models.
- [x] 2.3 Implement canonical stable ordering and checksum calculation for normalized graphs, including exact Workflow, Step, Gate, Side Effect, and Compensation versions.
- [x] 2.4 Extend the Harness workflow contract so exactly one explicit graph or legacy route declaration is active, while historical serialization remains readable through a versioned reader.
- [x] 2.5 Add round-trip, immutability, unsupported-type, checksum-collision, and graph-version compatibility tests for every new contract.

## 3. Graph Compiler and Preflight Validation

- [x] 3.1 Implement DSL lowering into normalized executable and control nodes, compiling Sequence to dependency edges and retaining explicit Choice, fork, join, loop guard, and Wait control points.
- [x] 3.2 Implement deterministic compilation of legacy ordered steps, entry step, routing rules, retry/repair bindings, gates, and side-effect policies into normalized Graph IR.
- [x] 3.3 Add structural validation for unique identities, valid endpoints, entry/terminal reachability, fork/join pairing, and cycles allowed only through Bounded-Loop.
- [x] 3.4 Add semantic validation for Choice priority/default, restricted condition paths/operators, positive loop bounds, Wait correlation/scope, and exact compensation binding.
- [x] 3.5 Add dataflow validation for reachable input producers, branch-scoped outputs, shared-write conflict rejection, explicit deterministic merge contracts, and terminal output availability.
- [ ] 3.6 Add registry validation for exact Worker type, Gate, Side Effect Handler, Compensation Handler, activity contract, and terminal policy references before `RUN_CREATED`.
- [x] 3.7 Add graph size/depth/node-activation policy validation and a deterministic preflight benchmark fixture for at least 1,000 nodes and 5,000 edges.
- [ ] 3.8 Add invalid-graph fixtures proving preflight records no run creation, Worker activity, side effect, or partial graph state.

## 4. Graph State, Node Identity, and Status Projection

- [ ] 4.1 Add `RunLifecycle`, `RunOutcome`, `HarnessNodeInstanceState`, join state, loop counter, Wait registration, compensation entry, and graph budget state models.
- [ ] 4.2 Implement deterministic node-instance identity from run, graph checksum, node definition, branch path, iteration vector, and persisted activation ordinal.
- [ ] 4.3 Implement immutable `HarnessGraphState` with stable ready/running/waiting/terminal projections, active activities, budget counters, graph reference, and last event sequence.
- [ ] 4.4 Enforce state invariants preventing one node instance from occupying incompatible states or accepting activity/gate evidence from another instance or attempt.
- [ ] 4.5 Implement canonical graph-state serialization and projection checksums covering every field that affects future scheduling decisions.
- [ ] 4.6 Implement the documented v1 status-to-v2 lifecycle/outcome reader and bounded public legacy-status projection, including halted versus indeterminate evidence.
- [ ] 4.7 Add state round-trip, deterministic identity, retry-versus-loop-instance, parallel-state, and compatibility projection tests.

## 5. Scheduler Decomposition and Pure Decision Logic

- [ ] 5.1 Extract the current per-step PLAN/EXECUTE/VERIFY/retry/replan/repair/halt logic into a pure `StepLifecycleStateMachine` without changing existing golden behavior.
- [ ] 5.2 Implement a pure `WorkflowGraphEvaluator` for Sequence readiness, deterministic Choice, fork/join facts, loop guard facts, Wait facts, compensation progress, and graph completion.
- [ ] 5.3 Retain `HarnessScheduler` as the single public decision facade and implement the documented deterministic arbitration priority across safety, step, graph, activation, waiting, and completion decisions.
- [ ] 5.4 Keep a single canonical decision per scheduler iteration and include pinned versions, input projection checksum, optional node-instance/attempt identity, stable reason code, and decision checksum.
- [ ] 5.5 Add purity tests proving scheduler components perform no Worker, Gate, clock, random, network, store, or mutable-global access.
- [ ] 5.6 Add deterministic permutation tests proving unordered inputs, equal timestamps, and repeated evaluation cannot change decision identity or order.
- [ ] 5.7 Add regression tests proving Worker route, winner, loop, verdict, compensation, approval, memory, and publication suggestions remain observational only.

## 6. Graph-Aware Control Plane Foundation

- [ ] 6.1 Update `HarnessControlPlane` initialization and preflight to pin one normalized graph and initialize graph-aware state before recording `RUN_CREATED`.
- [ ] 6.2 Add generic decision validation and application for node activation, graph control transitions, node terminal transitions, run waiting/completion, and halt without embedding business routing logic.
- [ ] 6.3 Preserve decision-before-transition durability and enforce projection checksum/version matching for every graph decision.
- [ ] 6.4 Ensure activity dispatch occurs only after its causal decision commits and bind each activity to node instance, attempt, idempotency key, fencing generation, and exact contract version.
- [ ] 6.5 Accept asynchronous activity results with duplicate-identical idempotency and reject stale, conflicting, cross-node, cross-attempt, cross-tenant, or cross-scope results.
- [ ] 6.6 Add atomic budget reservation/consumption transitions so concurrent branches cannot overspend stale run-level counters.
- [ ] 6.7 Implement recovery of committed-but-unprojected graph decisions and dispatched/completed activities without reconsulting a Worker or LLM.
- [ ] 6.8 Add fail-closed behavior proving canonical event-store failure prevents projection advancement and external activity dispatch.

## 7. Sequence and Choice Cutover

- [ ] 7.1 Execute normalized Sequence graphs through graph-aware Control Plane state while retaining exact Step lifecycle and Gate behavior.
- [ ] 7.2 Execute deterministic Choice control nodes with stable priority, one optional default, typed no-match failure, and durable branch selection before activation.
- [ ] 7.3 Compare legacy and graph-compiled decisions, outputs, gates, budgets, side effects, and terminal results for all linear and conditional golden fixtures.
- [ ] 7.4 Route the existing Research paper-analysis workflow through the graph executor without changing its Workers, Gates, Ports, publication contract, or result envelope.
- [ ] 7.5 Remove sequence/choice decisions from the old current-step routing execution once all repository callers use the graph path.

## 8. Parallel Execution and Data Isolation

- [ ] 8.1 Implement durable fork opening, deterministic branch scopes, stable activation admission, and Parallel-All join evidence.
- [ ] 8.2 Implement `fail_fast`, `wait_all`, and `compensate` Parallel-All failure policies with termination-confirmed cancellation semantics.
- [ ] 8.3 Implement Parallel-Any verified-success arbitration using authoritative stream sequence and commit the winner before downstream activation.
- [ ] 8.4 Implement loser cancellation, result reconciliation, aggregate-all-failed policy, and preservation of committed loser side effects.
- [ ] 8.5 Add node-instance-scoped branch output storage and exact branch output references.
- [ ] 8.6 Implement deterministic pure merge and verified aggregation-step integration; reject last-writer-wins and undeclared shared writes.
- [ ] 8.7 Add bounded physical activity dispatch controlled separately by `max_active_nodes` and `max_parallelism`, with stable admission order.
- [ ] 8.8 Enforce attempt termination, idempotency, and fencing readiness before permitting physical concurrency for an activity or side effect.
- [ ] 8.9 Add race, timeout, fail-fast, wait-all, all-failed, near-simultaneous winner, output-conflict, and crash-after-fork/join/winner tests.

## 9. Bounded Loop Execution

- [ ] 9.1 Implement durable loop entry, continuation, exit, exhaustion, and iteration counter transitions.
- [ ] 9.2 Create separate deterministic node instances and output scopes for each iteration while preserving retry attempts within one iteration.
- [ ] 9.3 Enforce loop-local `max_iterations` plus cumulative run-level turn, Worker-call, activation, retry, and replan budgets.
- [ ] 9.4 Add nested branch/loop scope tests, exact-bound tests, exhaustion-route tests, global-budget tests, and crash-between-iterations replay tests.

## 10. Durable Wait, Signal, Timer, and Approval

- [ ] 10.1 Add framework ports and immutable records for durable Wait registration, scoped signal inbox, timer wake, approval evidence, resume, timeout, and cancellation.
- [ ] 10.2 Implement signal identity, correlation, tenant/identity scope validation, duplicate idempotency, and bounded early-signal retention.
- [ ] 10.3 Implement Control Plane Wait registration-before-projection and scheduler resume/timeout decisions without direct interface or infrastructure access.
- [ ] 10.4 Integrate existing Harness approval resume semantics through the generic Wait contract while preserving exact approval evidence and side-effect authority.
- [ ] 10.5 Add a timer adapter that records wake outcomes as activities/events and never uses the current wall clock during replay.
- [ ] 10.6 Add Application Service operations for authorized signal, approval, cancellation, and inspection; interfaces MUST call these services rather than event stores or Control Plane internals.
- [ ] 10.7 Project Run lifecycle WAITING only when no runnable/running work remains and prove another parallel branch can continue while one Wait is unresolved.
- [ ] 10.8 Add process-restart, signal-before-registration, duplicate-signal, wrong-tenant, wrong-correlation, timeout, cancel, and timer-replay tests.

## 11. Explicit Compensation Runtime

- [ ] 11.1 Resolve exact compensation bindings during preflight and reject implicit, unknown, ambiguous, cyclic, or scope-incompatible bindings.
- [ ] 11.2 Push compensation entries only after the original side-effect outcome is durable and the originating executable node VERIFY succeeds.
- [ ] 11.3 Enter a dedicated compensation mode that stops forward scheduling and selects entries in reverse durable effect-commit sequence.
- [ ] 11.4 Execute each compensation as a bounded node instance through PLAN/EXECUTE/VERIFY with stable idempotency, fencing, Gate, budget, and outcome evidence.
- [ ] 11.5 Integrate terminal side-effect outcomes and parallel loser effects into the same compensation ordering without inferring inverse operations.
- [ ] 11.6 Implement `COMPENSATED`, `COMPENSATION_FAILED`, and `INDETERMINATE` terminal projections with explicit manual-intervention evidence.
- [ ] 11.7 Add crash-before/after compensation dispatch/outcome, duplicate recovery, partial compensation failure, budget exhaustion, parallel effect ordering, and offline replay tests.

## 12. Durable Events, Checkpoints, and Replay

- [ ] 12.1 Register versioned canonical data schemas for graph creation, activation, choice, fork, join, loop, Wait, winner, cancellation, compensation, budget, and lifecycle transitions without creating a second envelope or store.
- [ ] 12.2 Add pure reducers for every graph event and verify projection checksums after each applied stream sequence.
- [ ] 12.3 Extend checkpoints with graph version/checksum, node instances, active activities, join/loop/Wait/compensation state, budgets, last sequence, and projection checksum.
- [ ] 12.4 Extend `REBUILD_STATE` to restore graph state without live activities, effects, signals, timers, or clocks.
- [ ] 12.5 Extend `VERIFY_HISTORY` to rerun the pinned pure compiler/evaluator/state machine and compare decision checksums with recorded history.
- [ ] 12.6 Add v1 event/state/checkpoint readers and upcasters with corruption, unknown-version, missing-evidence, and incompatible-graph quarantine fixtures.
- [ ] 12.7 Add replay high-watermark, checkpoint-resume, Parallel winner, Wait wake, compensation, and no-live-fallback regression tests.

## 13. Inspection, Security, and Operations

- [ ] 13.1 Add graph-aware safe projections for lifecycle/outcome, node instances and phases, ready/running/waiting/terminal counts, branches, iterations, winners, joins, Waits, compensation, budgets, sequence, and terminal reasons.
- [ ] 13.2 Expose graph inspection through Application Services and preserve existing public business result envelopes during the bounded migration.
- [ ] 13.3 Apply schema-aware redaction, tenant scope, authorization, payload-reference, and bounded-diagnostic policy to graph events, checkpoints, inspection, logs, metrics, and traces.
- [ ] 13.4 Add low-cardinality metrics for active/ready/waiting nodes, parallel admission, loop iterations, Wait age, compensation progress, decision latency, replay mismatch, and graph validation failure.
- [ ] 13.5 Add operator diagnostics and health checks for stuck Waits, indeterminate activities, compensation failure, event lag, and incompatible history without exposing raw payloads.

## 14. Research Adoption and Compatibility Removal

- [ ] 14.1 Convert the Research workflow declaration to the explicit Graph DSL only after legacy-compiled graph equivalence is proven.
- [ ] 14.2 Introduce the first production `Parallel-All` across structure, contribution, and experiment analysis with branch-scoped outputs and an explicit verified aggregation contract.
- [ ] 14.3 Prove Research claim verification, quality gates, reader payload, paper card, terminal publication, artifacts, and result envelope remain semantically equivalent after parallelization.
- [ ] 14.4 Add v1/v2 mixed-history and status-projection tests for Research run inspection, recovery, artifact visibility, and latest accepted results.
- [ ] 14.5 Migrate all repository callers away from authoritative `current_step_id` and run-wide PLAN/EXECUTE/VERIFY statuses.
- [ ] 14.6 Delete the old routing executor, dual execution, dual write, deprecated cursor authority, and migration-only shims after all fixtures and repository callers pass.

## 15. Verification and Release Gates

- [ ] 15.1 Run focused Graph compiler, validator, state, scheduler, Control Plane, parallel, loop, Wait, compensation, event, replay, and migration test suites.
- [ ] 15.2 Run existing Harness, Research, API/application-service, architecture, side-effect, and deterministic gate regression suites without weakening assertions.
- [ ] 15.3 Run deterministic fault-injection at decision commit, projection, activity dispatch/result, fork, join, winner, loop boundary, Wait registration/resume, and every compensation boundary.
- [ ] 15.4 Run the graph preflight/readiness performance benchmark and document capacity results without weakening durable or deterministic semantics.
- [ ] 15.5 Run `python -m scripts.dev compile` and fix all root-cause failures.
- [ ] 15.6 Run mandatory `python -m scripts.dev smoke` and fix all root-cause failures.
- [ ] 15.7 Run `openspec validate harness-workflow-graph-runtime --strict` and resolve every schema or scenario error.
- [ ] 15.8 Execute and document rollback drills for crash after fork, before Parallel-Any winner, after Wait registration, and during compensation.
- [ ] 15.9 Record final implementation evidence, dependency versions, migration/upcast results, replay checksums, performance results, removed legacy paths, and residual operational limits.
