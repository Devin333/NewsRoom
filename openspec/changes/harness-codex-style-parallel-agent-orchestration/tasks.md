## 1. Group/Wave Contract and Policy Model

- [ ] 1.1 Define versioned `ParallelDispatchRequest`, `ParallelDispatchResult`, `DispatchGroup`, `DispatchWave`, group/wave status machines, join policy, and task-attempt identity models under the Harness task-plan boundary.
- [ ] 1.2 Extend the normalized dynamic-stage policy with explicit `join_policy`, `serial_fallback`, side-effect class/resource conflict key, group/wave limits, capability capacity, `ParentObservationLimits`, and parent/child budget reservation rules.
- [ ] 1.3 Add deterministic checksum projections for group/wave identity, ordered task identities, reservations, child result evidence, aggregate refs, and parent observation.
- [ ] 1.4 Add validator rules that reject candidate control fields, duplicate task identities, dependency violations, output collisions, unapproved capabilities/tools/memory, and policy widening before group admission.
- [ ] 1.5 Define canonical group/wave event names, transition owners, terminal states, idempotency keys, recovery actions, and at-least-once side-effect/reconciliation semantics.

## 2. Harness Fan-Out/Fan-In Coordinator

- [ ] 2.1 Implement the Harness-owned group/wave coordinator port and connect `TaskPlanStageRunner` to submit ready tasks as bounded dispatch waves.
- [ ] 2.2 Implement durable group admission and per-wave capacity/budget reservation before any child spawn, including idempotency for repeated admission requests and reservation release.
- [ ] 2.3 Compute effective parallelism from stage policy, capability capacity, concurrency reservations, and `ChildAgentSupervisor` capacity; leave overflow tasks in deterministic READY order within the same group.
- [ ] 2.4 Add explicit serial adapter and fail-closed behavior when parallel execution is required but no valid wave adapter is configured.
- [ ] 2.5 Implement deterministic group join waiting across multiple waves, `wait_all`/`fail_fast` behavior, required-role checks, output-conflict checks, and aggregate result publication.
- [ ] 2.6 Ensure group/wave coordinator never lets queue order, completion time, child output, or LLM text change workflow routing, quality, publication, memory, or outer-Graph state.

## 3. Child Runtime and Tool Boundary

- [ ] 3.1 Connect admitted task instances to `ChildAgentSupervisor` while preserving existing spawn, lease, heartbeat, cancel, close, and reclaim semantics.
- [ ] 3.2 Route each child attempt through `SubAgentRuntime`/`AgentRunner` with isolated input refs, context, tool allowlist, memory namespaces, transcript, budget, and attempt identity.
- [ ] 3.3 Reuse `ToolExecutor` and `ToolBatchExecutor` for child tool calls, and persist tool receipts/checksums under the owning child attempt.
- [ ] 3.4 Add deterministic result verification for group/wave/plan/task/attempt identity, transcript and artifact refs, output schema, tool/memory usage, and Research gates.
- [ ] 3.5 Add tests proving a child cannot select a worker, authorize tools, modify routing, publish, promote memory, or control sibling children.

## 4. AgentLoop Parent Delegation

- [ ] 4.1 Extend the action schema/parser with bounded `delegate_batch` candidates containing logical child proposals, dependencies, output roles, and correlation metadata.
- [ ] 4.2 Add the AgentLoop-to-Harness orchestration port and ensure AgentLoop submits candidates without creating threads, queues, concrete worker refs, or policy grants.
- [ ] 4.3 Convert legacy single `delegate` actions through a one-task group/wave compatibility adapter and preserve the current `AgentLoopResult` projection.
- [ ] 4.4 Materialize one security-projected joined observation for the parent turn, including stable group/wave summaries, refs/checksums, diagnostics, budget/recovery facts, and explicit `ParentObservationLimits`.
- [ ] 4.5 Add parent loop tests for valid multi-delegation, invalid control fields, excessive fan-out, partial failure, retry exhaustion, unavailable executor, and hidden-context redaction.

## 5. Planning and Tool Observations

- [ ] 5.1 Define a Harness-controlled two-stage planning-observation port: request/receipt first, then `PlanCandidate(source_observation_refs)` validation; invoke only policy-allowlisted read-only tools.
- [ ] 5.2 Persist planning tool receipts, planning budgets, correlation ids, and checksums; bind receipts first to `run_id/stage_id/planner_turn_id/policy_checksum`, then expose immutable source refs on the candidate.
- [ ] 5.3 Deny planner side-effect, publication, policy-change, and memory-promotion tools before execution with stable authorization diagnostics.
- [ ] 5.4 Add replay tests proving planning observations are read from durable receipts and never re-run live tools.
- [ ] 5.5 Add bounded planning limits: `max_planning_tool_calls`, `planning_timeout`, and planning retry behavior.

## 6. Research Dynamic Analysis Integration

- [ ] 6.1 Wire `build_dynamic_paper_analysis_workflow_spec()` and its composition factory to the real group/wave coordinator and `ChildAgentSupervisor`.
- [ ] 6.2 Update the Research dynamic policy/builder to declare policy-approved child tools and to retain `document`/`evidence_pack` input references without copying parent private context.
- [ ] 6.3 Dispatch independent `analysis.structure`, `analysis.contribution`, and `analysis.experiments` tasks through bounded fan-out, retaining existing per-role deterministic gates.
- [ ] 6.4 Implement deterministic Research aggregation into `analysis_branch_refs` and preserve the fixed `verify_claims` -> quality -> reader/card -> publication boundary.
- [ ] 6.5 Add production-composition checks that reject missing plan builder, wave adapter, worker binding, supervisor, durable store, artifact verifier, or tool port; allow serial fallback only when policy explicitly enables it.

## 7. Durable Events, Recovery, and Inspection

- [ ] 7.1 Add group/wave admission, dispatch, join-waiting, join-completed, retry, replan, cancel, reclaim, and recovery event types/projections with parent run correlation.
- [ ] 7.2 Extend checkpoints and transcript receipts with group/wave/join state, reservations, per-attempt evidence, aggregate checksum, and event stream sequence.
- [ ] 7.3 Implement crash reconciliation for missing dispatch/result/join transitions and receipt reuse without duplicate child, tool, or external side-effect execution.
- [ ] 7.4 Implement lease-expiry handling for indeterminate child outcomes and bounded reclaim/retry according to the pinned policy.
- [ ] 7.5 Add security-projected inspection and metrics for requested/effective parallelism, queue/wait/run/join durations, child states, budget usage, retry/replan counts, recovery outcome, and `DEGRADED_SERIAL` reason.
- [ ] 7.6 Add offline replay tests for accepted, partially failed, cancelled, serial-fallback, and crash-recovered groups; assert no live LLM/tool/worker/queue calls.

## 8. Verification, Rollout, and Documentation

- [ ] 8.1 Add focused unit tests for candidate validation, admission idempotency, capacity reservation, deterministic ordering, join aggregation, output conflict, and bounded retry/replan.
- [ ] 8.2 Add integration tests using a fake supervisor/worker to prove two or more independent children MUST overlap in execution when concurrency conditions hold, while dependency tasks wait; also cover multi-wave group join.
- [ ] 8.3 Add Research dynamic publication regression and static-workflow-default regression tests.
- [ ] 8.4 Run `openspec validate harness-codex-style-parallel-agent-orchestration --strict` and resolve every validation error.
- [ ] 8.5 Run targeted Harness, AgentLoop, tool-runtime, supervisor, and Research tests, then run the repository compile/smoke checks required by the affected modules.
- [ ] 8.6 Enable the generic AgentLoop orchestration port behind a feature flag, then enable it only for the opt-in dynamic Research workflow; capture telemetry/replay evidence and document serial fallback/rollback before any default switch.
