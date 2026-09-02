## 1. Evidence and Ownership

- [ ] 1.1 Lock the implementation baseline: record `HEAD`, branch, porcelain status, active OpenSpec state, and caller inventory for every P0/P1 finding.
- [ ] 1.2 Turn each P0/P1 finding into a minimal failing runner/integration test before changing production code.
- [ ] 1.3 Classify every P2 item as `runtime_reproduced`, `contract_reproduced`, or `coverage_gap`; assign an owner change and due disposition.

## 2. P0 Activity Terminal Safety

- [ ] 2.1 Make started timeout/cancel/indeterminate activity outcomes produce typed worker evidence and durable terminal result events.
- [ ] 2.2 Preserve cancellation, timeout, termination confirmation and reason-code distinctions through committer, projection, recovery and replay.
- [ ] 2.3 Prevent recovery/reconcile from redispatching an activity with `termination_confirmed=False` until verified termination or explicit repair.
- [ ] 2.4 Add real dispatcher/committer integration tests for hanging worker, cooperative cancellation, timeout, recovery and no duplicate physical invocation.
- [ ] 2.5 Complete or explicitly block the related `harness-runtime-execution-safety` 5.1-5.4 evidence without fabricating deployment qualification.

## 3. TaskPlan Integrity

- [ ] 3.1 Design and implement explicit replacement state/mapping in plan, projection, events and replay; preserve historic plan immutability.
- [ ] 3.2 Validate replacement output role and require atomic dependency rewire or typed rejection for downstream consumers.
- [ ] 3.3 Make aggregation and blocked detection exclude replaced/skipped historic failures while preserving genuine pending/blocked diagnostics.
- [ ] 3.4 Enforce `retryable_reason_codes` in live runner, recovery and replay; define empty-list behavior and migration diagnostics.
- [ ] 3.5 Expose actual gate registry refs to PLAN validation and fail closed before worker dispatch on missing gates.
- [ ] 3.6 Align InMemory and durable `results_for` semantics with a parameterized store contract matrix.
- [ ] 3.7 Add replacement-to-verified, retryable/non-retryable, missing gate, durable replay and recovery runner tests.

## 4. Policy and Data Integrity

- [ ] 4.1 Route ToolExecutor approval and trace logic through `ToolPolicy.requires_approval`.
- [ ] 4.2 Treat missing/untrusted MCP risk metadata as approval-required or blocked; add operator-owned classification design and tests.
- [ ] 4.3 Fix shared secret patterns and typed LLM field redaction; add shared negative/positive golden vectors across all consumers.
- [ ] 4.4 Remove candidate-owned skill approval evidence; require resolver-backed approval and real evaluation cases.
- [ ] 4.5 Route all MemoryRuntime promote/mutation/invalidation/forget operations through one policy decision path and revalidate target records.
- [ ] 4.6 Add adversarial Tool/MCP, redaction, skill and memory policy behavior tests.

## 5. Side Effects and P2 Runtime Closure

- [ ] 5.1 Define recovery behavior for serial side effects without durable outcome: idempotent retry/reconcile versus indeterminate quarantine.
- [ ] 5.2 Fix child supervisor cancel lock scope, InMemory queue fencing and terminal wait binding retention.
- [ ] 5.3 Propagate AttemptContext deadline/cancel to OpenAI-compatible complete/stream retry loops.
- [ ] 5.4 Enforce artifact reference checksum on resolver/replay and package-root containment/hash coverage for skill schemas.
- [ ] 5.5 Separate canonical context event commits from runtime projection sink failures; preserve durable event recovery error classes.
- [ ] 5.6 Replace tautological/weak test oracles with exact AST, behavior and exception-path assertions.
- [ ] 5.7 Record caller evidence for P2 public APIs that remain unconnected to production composition.

## 6. Verification and Release

- [ ] 6.1 Run focused suites for activity runtime, TaskPlan, Tool/MCP, redaction, MemoryRuntime, skill evolution, side effect recovery and affected P2 owners.
- [ ] 6.2 Run `.\.venv\Scripts\python.exe -m scripts.dev compile` and `.\.venv\Scripts\python.exe -m scripts.dev smoke`; fix root causes for failures.
- [ ] 6.3 Run `openspec validate framework-runtime-audit-repair --strict`, `openspec validate harness-runtime-execution-safety --strict`, and `openspec validate --all --strict`.
- [ ] 6.4 Save evidence containing commands, output summary, caller inventory, platform/deployment blockers, migration compatibility and path-scoped commits.
- [ ] 6.5 Review the final diff for unauthorized fallback paths, LLM-controlled authority, raw secret/event leakage, and unrelated worktree modifications before commit.
