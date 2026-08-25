## 1. Existing Contract Closure

- [ ] 1.1 Complete `model-aware-llm-context-preflight` tasks 7.1-7.6 with focused tests, compile, smoke, strict validation, redaction/dependency audit, evidence, and path-scoped commit.
- [x] 1.2 Audit `source-policy-contract-convergence` current composition against the live tree and update stale evidence before changing task status.
- [x] 1.3 Bind API, MCP, worker, CLI, Source-tool registry/Harness, and Research package/PDF paths to the intended `SourceRuntimeComposition`, with an explicit unsupported-capability decision for the absent Harness Source ToolPort.
- [x] 1.4 Add consecutive-call quota and no-network typed-denial tests for every Source entry surface, including Research package/PDF factories; complete source evidence task 3.10 and 7.5.
- [x] 1.5 Record `durable-event-runtime` 9.5 and `harness-workflow-graph-runtime` 1.1 as external production qualification blockers without fabricating governance signatures, deployment observations, or rollback evidence.

## 2. Execution Environment Contract

- [x] 2.1 Add immutable execution profile, capability profile, request, receipt, and typed failure models under framework-owned contracts.
- [x] 2.2 Add `ExecutionEnvironmentPort` and provider registry with `trusted_in_process` versus `sandboxed_process` admission; missing required capability fails closed.
- [x] 2.3 Implement the first process provider with canonical filesystem roots, environment allowlist, process-tree/job control, resource limits, and bounded cancellation confirmation.
- [x] 2.4 Add provider capability checks for network deny/allowlist and reject profiles that the deployment cannot physically enforce; do not use policy-only fallback.
- [x] 2.5 Route sandboxed `ToolExecutor` calls through the environment port and preserve existing Graph identity, approval, redaction, artifact, retry, and event contracts.
- [x] 2.6 Add Windows and POSIX path adversarial tests for traversal, drive-relative, UNC, symlink/junction escape, undeclared writes, and protected environment variables.

## 3. Child Agent Supervisor

- [x] 3.1 Add immutable `ChildAgentHandle`, lifecycle state model, operation identity, lease, heartbeat, and terminal receipt contracts.
- [x] 3.2 Implement `spawn`, `status`, `wait`, `cancel`, and `close` through a Harness-owned supervisor with Graph budget and capability admission.
- [x] 3.3 Bind child output to exact parent/child Graph identity and reject routing, quality, publication, memory, skill, and sibling-control fields.
- [x] 3.4 Persist child lifecycle and heartbeat events; implement stale lease detection, bounded reclaim, idempotent cancellation, and confirmed termination handling.
- [x] 3.5 Add parent restart recovery that reuses committed results, reattaches only with verified ownership, and fails closed for ambiguous side effects.
- [x] 3.6 Add lifecycle, capacity, duplicate-operation, identity-tamper, stale-lease, restart, cancellation, and no-duplicate-side-effect tests.

## 4. Unified Runtime Event Projection

- [x] 4.1 Define canonical runtime event schemas for turn, tool, approval, context compaction, worker, and child-agent lifecycle facts.
- [x] 4.2 Add redaction, bounded refs/checksums, stable reason codes, event identity, and Graph/activity/attempt binding before durable append.
- [x] 4.3 Implement idempotent projection consumer with checkpoint/cursor resume, ordered per-stream reads, and rebuild without live side effects.
- [x] 4.4 Adapt ToolExecutor, approval/wait runtime, AgentLoop/turn runtime, ContextCompactionRuntime, worker service, and ChildAgentSupervisor to emit the canonical facts.
- [x] 4.5 Add read-only operator status/timeline service and API/SDK queries; keep mutations on existing application-service approval/cancel/resume ports.
- [x] 4.6 Add duplicate delivery, redaction, cursor conflict, projection rebuild, event identity mismatch, and no-routing-authority tests.

## 5. Cross-Cutting Verification And Release

- [ ] 5.1 Add process restart, tool timeout, child loss, cancellation uncertainty, and external side-effect deduplication scenarios to the relevant integration suites.
- [ ] 5.2 Run architecture and production-caller scans proving every sandboxed tool and child lifecycle path enters Harness-owned ports.
- [ ] 5.3 Run focused tests, `python -m scripts.dev compile`, `python -m scripts.dev smoke`, `openspec validate harness-runtime-execution-safety --strict`, and `openspec validate --all --strict`.
- [ ] 5.4 Produce deployment capability evidence for each enabled execution provider, including unsupported capability rejection and rollback behavior.
- [x] 5.5 Update PRD/evidence with exact test commands, skips, runtime qualification status, and path-scoped commit references; do not claim completion from documentation alone.
