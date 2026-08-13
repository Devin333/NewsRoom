## 1. Contracts and Golden Fixtures

- [x] 1.1 Add versioned schema identifiers and canonical serialization helpers for TaskPlan, TaskPlanPatch, task definitions, task instances, and projections.
- [x] 1.2 Implement immutable `TaskSpec`, `PlanCandidate`, `ResolvedTaskSpec`, `ValidatedTaskPlan`, `PlanPatch`, `TaskPlanPolicy`, and limits/result reference models.
- [x] 1.3 Add construction-time validation for required ids, refs, versions, finite budgets, stable collections, JSON compatibility, and forbidden executable fields.
- [x] 1.4 Add deterministic checksum fixtures for valid candidates, accepted plans, patches, policies, task definitions, and task projections.
- [x] 1.5 Add malformed and unsupported schema/version fixtures that prove fail-closed parsing.

## 2. Policy and Candidate Validation

- [x] 2.1 Add a pinned `TaskPlanPolicy` registry with duplicate, unknown, ambiguous, and incompatible-version rejection.
- [x] 2.2 Implement recursive forbidden-field validation across candidate task, output contract, acceptance criteria, diagnostics, and metadata payloads.
- [x] 2.3 Implement DAG validation for unique ids, dependency existence, self-loop, cycle, reachability, depth, and at least one executable root.
- [x] 2.4 Implement stage-boundary and dataflow validation for allowed inputs, same-stage dependencies, output roles, producer reachability, and future-stage reference rejection.
- [x] 2.5 Implement output-conflict validation that requires unique roles or an exact registered deterministic aggregator.
- [x] 2.6 Implement policy intersection for requested tools, memory namespaces, task retry, task count, depth, parallelism, plan-builder calls, and aggregate budget.
- [x] 2.7 Return stable bounded validation diagnostics and ensure validation failure creates no dispatch, queue, or worker activity.

## 3. Plan Builder and Capability Binding

- [x] 3.1 Define `PlanCandidateBuilderPort` and a Harness LLM adapter that exposes only policy-approved stage context references.
- [x] 3.2 Parse plan-builder output into `PlanCandidate` without accepting worker refs, callables, authorization, routing, quality, memory, or publication fields.
- [x] 3.3 Add a capability registry that resolves one allowlisted capability to one pinned worker/SubAgent binding and contract version.
- [x] 3.4 Reuse existing SubAgent context, tool, memory, budget, schema, transcript, and forbidden-result gates for resolved dynamic tasks.
- [x] 3.5 Reject missing, ambiguous, stale, or incompatible worker bindings before plan acceptance or task dispatch.
- [x] 3.6 Add fake plan builder, fake capability registry, and fake resolved workers for deterministic framework tests.

## 4. Accepted Plan and Projection Storage

- [x] 4.1 Define `TaskPlanStorePort` for candidate refs, accepted plan versions, patches, task results, and current projection reads.
- [x] 4.2 Add an in-memory TaskPlan store for deterministic tests with version conflict and checksum enforcement.
- [x] 4.3 Add production composition against existing durable event/artifact/result ports without creating a second event store.
- [x] 4.4 Implement atomic version-1 plan acceptance with pinned graph/policy refs, normalized task bindings, budget snapshot, and plan checksum.
- [x] 4.5 Implement monotonic plan-version conflict rejection and immutable history access for earlier accepted versions.
- [x] 4.6 Implement pure reducers for plan, task, attempt, result, budget, patch, aggregation, and stage-terminal events.

## 5. Deterministic Scheduling and Queue Projection

- [x] 5.1 Implement pure ready-task calculation from dependency success, input availability, binding validity, task state, and budget reservation.
- [x] 5.2 Implement stable ready ordering by priority, dependency depth, task id, and task checksum.
- [x] 5.3 Enforce `max_parallelism`, active task, worker capacity, and run/stage budget bounds independently from logical readiness.
- [x] 5.4 Materialize ready work into existing generic queue `Task` records carrying run/stage/plan/task/attempt identity metadata only.
- [x] 5.5 Keep DAG dependency, plan version, accepted output, and replay authority in TaskPlan projection rather than queue records.
- [x] 5.6 Handle duplicate delivery, missing queue projection, lease reclaim, stale task, and idempotent recreation from durable readiness.

## 6. Task Execution, Verification, and Aggregation

- [x] 6.1 Allocate deterministic task-instance, attempt, idempotency, and fencing identities before dispatch.
- [x] 6.2 Commit causal ready/dispatch events and budget reservation before invoking any dynamic worker.
- [x] 6.3 Validate returned run, stage, plan, task, attempt, binding, output, artifact refs, usage, and checksums before accepting results.
- [x] 6.4 Reject stale-plan, wrong-attempt, duplicate-conflicting, wrong-binding, unauthorized-tool, invalid-memory, and forbidden-control results.
- [x] 6.5 Execute only the exact task gates and dependencies pinned by the accepted plan and policy in stable order.
- [x] 6.6 Add a deterministic aggregator registry and stable role-based aggregation over accepted result references.
- [x] 6.7 Reject missing required roles, ambiguous producers, schema mismatches, and implicit last-writer-wins before stage success.

## 7. Retry, PlanPatch, and Controlled Halt

- [x] 7.1 Implement task retry decisions within normalized attempt and budget limits while preserving task definition identity.
- [x] 7.2 Define and validate v1 patch operations: add replacement task, skip eligible pending task, and update dependencies of not-started tasks.
- [x] 7.3 Enforce `base_plan_version`, atomic patch validation, full DAG/dataflow/policy revalidation, and incremental budget reservation.
- [x] 7.4 Prevent patches from editing running/completed tasks, committed results, required roles, policies, gates, publication, side effects, or the outer graph.
- [x] 7.5 Commit accepted patch version N+1 and recompute readiness without rerunning completed non-deterministic activity.
- [x] 7.6 Add typed controlled outcomes for retry exhaustion, replan exhaustion, unavailable binding, missing required output, integrity failure, and event-store failure.

## 8. Harness Lifecycle Integration

- [x] 8.1 Add the explicit TaskPlan stage binding or `HarnessWorkerType.TASK_PLAN` with exact reader, compiler, binding-authority, serialization, and version validation support.
- [x] 8.2 Integrate candidate build/validate/accept into the dynamic node's outer `PLAN` phase.
- [x] 8.3 Integrate ready calculation, bounded dispatch, worker collection, retry, and patch into the outer `EXECUTE` phase.
- [x] 8.4 Integrate deterministic task gates, aggregation, and stage output verification into the outer `VERIFY` phase.
- [x] 8.5 Keep `HarnessScheduler` as the single Control Plane decision facade and prevent TaskPlan components or business code from directly applying transitions.
- [x] 8.6 Ensure graph checksum and node-instance identity remain unchanged across plan versions and patch cycles.
- [x] 8.7 Add preflight validation that rejects dynamic stage declarations without exact policy, builder, binding, gate, aggregator, event, checkpoint, and result-store support.

## 9. Durable Events, Checkpoint, Replay, and Inspection

- [x] 9.1 Add versioned canonical events for candidate build/reject, plan accept, task ready/dispatch/start/result/terminal, retry, patch, aggregation, verify, and halt.
- [x] 9.2 Register new event schemas in the existing schema catalog and keep payloads reference-based and security-projected.
- [x] 9.3 Extend graph checkpoints with plan version/checksum, task/attempt states, ready ordering, accepted output refs, budgets, retries, replans, and last sequence.
- [x] 9.4 Extend recovery to resume accepted plans, recreate missing queue projections, and avoid regenerating candidates or rerunning committed results.
- [x] 9.5 Extend replay reducers and decision verification to consume recorded plans, patches, task results, aggregations, and pinned versions without live I/O.
- [x] 9.6 Add fail-closed diagnostics for missing schema, policy, binding, plan artifact, result ref, event, sequence, or checksum mismatch.
- [x] 9.7 Extend authorized run inspection with policy, candidate/plan/patch refs, task states/dependencies/attempts, budgets, failures, outputs, and replay verdict.
- [x] 9.8 Add bounded metrics and traces for validation, plan versions, task lifecycle, retry/replan, budget, stale/duplicate results, and replay without high-cardinality private payloads.

## 10. Research Dynamic Analysis Pilot

- [x] 10.1 Define the Research `research.analysis` TaskPlan policy with fixed `document`/`evidence_pack` inputs and required structure/contribution/experiments output roles.
- [x] 10.2 Register allowlisted Research capabilities against existing SubAgentSpec/worker implementations and exact deterministic gates.
- [x] 10.3 Implement the deterministic Research stage aggregator that produces the existing `analysis_branch_refs` contract.
- [x] 10.4 Add `build_dynamic_paper_analysis_workflow_spec()` with a distinct workflow/graph id and fixed `dynamic_analysis_stage` between evidence and `verify_claims`.
- [x] 10.5 Keep `build_paper_analysis_workflow_spec()` unchanged and preserve it as the default production workflow selection.
- [x] 10.6 Wire dynamic output through existing `verify_claims`, `ResearchQualityGate`, reader payload, paper card, terminal side-effect policy, and artifact publication.
- [x] 10.7 Reject Research candidates that reference future steps, skip source/evidence, create publication/quality/memory tasks, or omit required roles.
- [x] 10.8 Add production composition validation that never substitutes fake plan builders, fake subagents, legacy paper-radar dependencies, or in-memory-only stores.

## 11. Automated Verification

- [x] 11.1 Add model, schema, canonical serialization, checksum, forbidden-field, and unsupported-version unit tests.
- [x] 11.2 Add validator tests for cycles, depth, reachability, unknown dependencies, stage leaks, binding ambiguity, role conflicts, tools, memory, and budget.
- [x] 11.3 Add scheduler tests for deterministic order, parallel bounds, dependency completion, budget reservation, queue loss, duplicate delivery, and lease reclaim.
- [x] 11.4 Add result tests for stale plan, wrong attempt, wrong binding, duplicate-identical, duplicate-conflicting, gate failure, and committed result reuse.
- [x] 11.5 Add retry/patch tests for accepted replacement, stale base version, illegal completed-task edit, incremental budget, immutable history, and replan exhaustion.
- [x] 11.6 Add crash-point tests around plan acceptance, dispatch event, worker start, result commit, patch accept, aggregation, and outer VERIFY transition.
- [x] 11.7 Add replay tests proving no live planner/worker/tool/queue calls and matching plan/task/output/decision checksums.
- [x] 11.8 Add Research fake-LLM/fake-subagent E2E tests for valid dynamic analysis, dependency fan-out, missing role, replacement task, gate failure, and publication blocking.
- [x] 11.9 Add static/dynamic Research result-envelope, gate, artifact-ref, inspection, and replay parity fixtures.
- [x] 11.10 Run existing Graph Runtime, SubAgent Runtime, Research runtime, event/checkpoint/replay, queue, and interface regression suites.

## 12. Delivery Gates and Documentation

- [x] 12.1 Document the TaskPlan schema, capability registry, policy authoring, dynamic stage lifecycle, events, inspection, and operator recovery behavior.
- [x] 12.2 Document the Research dynamic workflow opt-in boundary and static-workflow rollback procedure.
- [x] 12.3 Run `python -m scripts.dev compile` and fix all compile/import/type failures caused by the change.
- [x] 12.4 Run focused TaskPlan and Research suites, then `python -m scripts.dev test`, and fix root causes for all failures.
- [x] 12.5 Run `python -m scripts.dev smoke` and deterministic replay/crash recovery drills.
- [x] 12.6 Run `openspec validate harness-dynamic-task-planning --strict` and resolve every proposal/spec/task validation error.
- [x] 12.7 Verify no production `framework/harness` import crosses into `business`, `interfaces`, or `infrastructure`, and no Research import uses legacy paper-radar modules.
- [x] 12.8 Review and remove obsolete static-analysis compatibility code only when the dynamic variant is explicitly promoted; do not remove the current default static workflow in this change.
