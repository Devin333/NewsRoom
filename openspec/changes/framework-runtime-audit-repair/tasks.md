## 1. Evidence and Ownership

- [x] 1.1 Lock the implementation baseline: record `HEAD`, branch, porcelain status, active OpenSpec state, and caller inventory for every P0/P1 finding. Evidence: `evidence/implementation.md`.
- [x] 1.2 Turn each P0/P1 finding into a minimal failing runner/integration test before changing production code. The resulting regression tests and their scope are recorded in `evidence/implementation.md`.
- [x] 1.3 Classify every P2 item as `runtime_reproduced`, `contract_reproduced`, or `coverage_gap`; assign an owner change and due disposition. The matrix is recorded in `evidence/implementation.md`.

## 2. P0 Activity Terminal Safety

- [x] 2.1 Make started timeout/cancel/indeterminate activity outcomes produce typed worker evidence and durable terminal result events.
- [x] 2.2 Preserve cancellation, timeout, termination confirmation and reason-code distinctions through committer, projection, recovery and replay.
- [x] 2.3 Prevent recovery/reconcile from redispatching an activity with `termination_confirmed=False` until verified termination or explicit repair.
- [x] 2.4 Add real dispatcher/committer integration tests for hanging worker, cooperative cancellation, timeout, recovery and no duplicate physical invocation.
- [ ] 2.5 Status: blocked by the inherited `harness-runtime-execution-safety` tasks 5.1-5.4 (process-restart integration, production-caller scan, focused full smoke qualification, and deployment capability/rollback evidence). No deployment qualification is claimed; see `evidence/implementation.md`.

## 3. TaskPlan Integrity

- [x] 3.1 Design and implement explicit replacement state/mapping in plan, projection, events and replay; preserve historic plan immutability.
- [x] 3.2 Validate replacement output role and require atomic dependency rewire or typed rejection for downstream consumers.
- [x] 3.3 Make aggregation and blocked detection exclude replaced/skipped historic failures while preserving genuine pending/blocked diagnostics.
- [x] 3.4 Enforce `retryable_reason_codes` in live runner, recovery and replay; define empty-list behavior and migration diagnostics.
- [x] 3.5 Expose actual gate registry refs to PLAN validation and fail closed before worker dispatch on missing gates.
- [x] 3.6 Align InMemory and durable `results_for` semantics with a parameterized store contract matrix.
- [x] 3.7 Add replacement-to-verified, retryable/non-retryable, missing gate, durable replay and recovery runner tests.

## 4. Policy and Data Integrity

- [x] 4.1 Route ToolExecutor approval and trace logic through `ToolPolicy.requires_approval`.
- [x] 4.2 Treat missing/untrusted MCP risk metadata as approval-required or blocked; add operator-owned classification design and tests.
- [x] 4.3 Fix shared secret patterns and typed LLM field redaction; add shared negative/positive golden vectors across all consumers.
- [x] 4.4 Remove candidate-owned skill approval evidence; require resolver-backed approval and real evaluation cases.
- [x] 4.5 Route all MemoryRuntime promote/mutation/invalidation/forget operations through one policy decision path and revalidate target records.
- [x] 4.6 Add adversarial Tool/MCP, redaction, skill and memory policy behavior tests.

## 5. Side Effects and P2 Runtime Closure

- [ ] 5.1 Status: deferred to `harness-side-effect-authority-closure`; owner: side-effect runtime; trigger: serial external handler composition; target: durable outcome or explicit indeterminate/reconcile contract. Current focused side-effect recovery coverage is recorded in `evidence/implementation.md`.
- [ ] 5.2 Status: deferred to `harness-runtime-lifecycle-hardening`; owner: lifecycle runtime; trigger: approval-required executable nodes, queue lease fencing, child cancel/join, or wait-binding production composition.
- [ ] 5.3 Status: deferred to `llm-openai-compatible-runtime-hardening`; owner: LLM client; trigger: production OpenAI-compatible composition requiring `AttemptContext` deadline/cancel propagation.
- [ ] 5.4 Status: deferred to `artifact-skill-integrity-hardening`; owner: artifact and skill storage; trigger: resolver/replay or skill package loading in production composition.
- [ ] 5.5 Status: completed by the inherited canonical event/projection runtime contract; no new authority path is introduced. Evidence and residual release blockers are recorded in `evidence/implementation.md`.
- [ ] 5.6 Status: deferred to `framework-runtime-test-oracle-hardening`; owner: test architecture; trigger: new production roots or a weak-oracle audit finding. This change adds exact negative and exception-path assertions for the P0/P1 scope.
- [x] 5.7 Record caller evidence for P2 public APIs that remain unconnected to production composition. See the caller inventory and P2 matrix in `evidence/implementation.md`.

## 6. Verification and Release

- [x] 6.1 Run focused suites for activity runtime, TaskPlan, Tool/MCP, redaction, MemoryRuntime, skill evolution, side effect recovery and affected P2 owners.
- [ ] 6.2 Status: blocked for release qualification because `scripts.dev smoke` exceeded the bounded wall-clock window after the focused portions ran; compile passed and the exact timeout evidence is recorded in `evidence/implementation.md`.
- [x] 6.3 Run `openspec validate framework-runtime-audit-repair --strict`, `openspec validate harness-runtime-execution-safety --strict`, and `openspec validate --all --strict`.
- [x] 6.4 Save evidence containing commands, output summary, caller inventory, platform/deployment blockers, migration compatibility and path-scoped commits.
- [x] 6.5 Review the final diff for unauthorized fallback paths, LLM-controlled authority, raw secret/event leakage, and unrelated worktree modifications before commit.
