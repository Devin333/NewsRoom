## 1. Baseline and contract inventory

- [ ] 1.1 Freeze the current baseline: record date, `HEAD`, all related OpenSpec counts, existing safety receipts, and the supported production entrypoints; label the values as a snapshot rather than live status.
- [ ] 1.2 Complete or explicitly hand off `harness-runtime-execution-safety` tasks 5.1-5.4, mapping each predecessor evidence item to this change without duplicate completion claims.
- [ ] 1.3 Produce a versioned production-runtime caller inventory for `ToolExecutor`, `ExecutionEnvironment`, `subprocess`, `SubAgentRuntime`, `ChildAgentSupervisor`, runtime event sink, projection, and operator service construction sites; classify each as migrate, trusted exemption, or blocked. Every exemption must name an owner, rationale, non-Harness-managed proof, expiry/review date, and test/static check.
- [ ] 1.4 Define the capability/profile registry for `trusted_in_process`, `sandboxed`, and `external_process`, including unsupported Docker capabilities, outbound MCP/sidecar network/credential requirements, and stable typed denial codes.

## 2. Production execution composition (P0)

- [ ] 2.1 Implement a versioned `RuntimeCompositionManifest` and one `RuntimeExecutionComposition` per process at the application composition boundary. Bind composition/policy/provider fingerprints, execution registry, durable intent/receipt repository, child lease/receipt repository, idempotency/reconciliation port, event/outbox publisher, projection checkpoint reader, operator authorizer, and operator service.
- [ ] 2.2 Wire API, worker, CLI, Harness, and Research entrypoints to resolve the same manifest fingerprint; reject startup/health/admission on composition drift and remove local provider/registry/event-authority construction from production paths.
- [ ] 2.3 Inject the execution environment into `AgentRunner`, Harness tool activity, batch executor, and every external `ToolExecutor` path; make external activity admission fail closed by default.
- [ ] 2.4 Convert Research parser/PDF compiler and other approved direct process callers to execution adapters carrying cwd, mounts, env, timeout, cancellation, and receipt mapping.
- [ ] 2.5 Separate inbound MCP server routing from outbound `ToolRuntime` MCP adapter/sidecar execution; only outbound activity enters execution admission with explicit network, credential, timeout, and cancellation capabilities.
- [ ] 2.6 Add startup/admission diagnostics for provider unavailable, capability unsupported, Graph identity mismatch, invalid profile, manifest drift, and durable store unavailable; verify no host-process fallback.
- [ ] 2.7 Add a production caller scan that fails on unapproved direct subprocess, raw external tool execution, direct child launch, or executor construction without composition injection.

## 3. Harness-owned child dispatch (P1)

- [ ] 3.1 Adapt the existing child worker runtime behind `ChildAgentSupervisor` and route Research/Harness child dispatch through the supervisor as the only lifecycle owner. Launch/terminate production children only through admitted `ExecutionEnvironment` adapters.
- [ ] 3.2 Bind parent/child/lease/attempt/Graph identity to durable execution receipts, child receipts, transcript/output refs, heartbeat facts, and canonical lifecycle events.
- [ ] 3.3 Implement restart recovery from durable leases and receipts, including completed, resumable, `LOST`, `INDETERMINATE`, quarantine, and manual-repair outcomes.
- [ ] 3.4 Verify idempotent `spawn/status/wait/heartbeat/cancel/close` across repeated and conflicting requests; reject a second lifecycle owner.
- [ ] 3.5 Add tests for heartbeat timeout, child process loss, confirmed cancellation, ambiguous cancellation, close-after-restart, and no repeated side effects.

## 4. Canonical durable runtime event transport (P1)

- [ ] 4.1 Bind `CanonicalRuntimeEventPublisher` to the durable event runtime and transactional/recoverable outbox; make projection consume canonical events rather than direct module writes.
- [ ] 4.2 Project turn, tool, approval, compaction, child, worker heartbeat, timeout, cancel, indeterminate, and terminal facts with stable scope, store-assigned per-run sequence, checksum, schema, and redaction metadata.
- [ ] 4.3 Implement cursor encoding/versioning for run/Graph scope, sequence, and principal/tenant fingerprint; wire default operator status/timeline services and API/MCP/CLI read paths to authenticate and authorize before reading.
- [ ] 4.4 Route approval requested/decided/rejected/expired through the Harness approval service, deterministic authorizer, authoritative receipt, idempotency key, and canonical outbox; reject direct worker/operator approval writes.
- [ ] 4.5 Add duplicate delivery, concurrent publisher, projection rebuild/checkpoint, sequence conflict, cross-run/principal cursor, redaction, authorization audit, and read-only authority tests.
- [ ] 4.6 Verify the event path does not allow worker/LLM/operator data to become routing, approval, authorization, memory-write, or publication decisions.

## 5. Recovery and qualification (P2)

- [ ] 5.1 Implement and test the versioned `PREPARED -> DISPATCHED -> RECEIPT_COMMITTED -> EVENT_PUBLISHED` intent/outbox/receipt state machine, including recovery at every crash boundary.
- [ ] 5.2 Add crash/restart integration tests at execution, child dispatch, event publish, projection apply, and side-effect receipt boundaries.
- [ ] 5.3 Add timeout/termination tests that verify process cleanup, termination confirmation, and indeterminate classification when confirmation is unavailable.
- [ ] 5.4 Add idempotency/reconciliation tests proving identical receipts are replayed, conflicting bodies fail, dispatch-without-receipt is never blindly retried, and receipt-without-event only replays the outbox.
- [ ] 5.5 Run focused tests, compile, appropriate smoke, strict validation for this change and related changes; record commands and results in evidence.
- [ ] 5.6 Produce a deployment capability matrix for Docker, durable event store, secret provider, network policy, child limits, and rollback observer; mark unavailable capabilities as blocked.
- [ ] 5.7 Create and maintain `openspec/changes/harness-runtime-production-composition/evidence.md` with baseline, manifest/provider fingerprints, commands, environment capabilities, pass/skip/block classifications, real receipt/event refs, and external signature state.
- [ ] 5.8 Complete an independent production/restart/rollback evidence review; do not close tasks that require external signatures without the real signature chain.

## 6. Documentation and handoff

- [ ] 6.1 Update the PRD/design/evidence with final composition ownership, migration flags, supported profiles, and known blockers.
- [ ] 6.2 Verify no stale documentation claims in-memory projection, optional provider injection, or old child runtime as the default production path.
- [ ] 6.3 Commit the change with path-scoped staging after strict validation and attach the final test/capability evidence.
