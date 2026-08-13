## 1. Versioned Subagent Evidence Contracts

- [ ] 1.1 Add explicit TaskPlan attempt identity and accepted observation fields to `SubAgentInvocation`, and replace bare `SubAgentResult.transcript_ref` ownership with typed receipt evidence. (AST-FR-001, AST-FR-004)
- [ ] 1.2 Implement strict versioned `SubAgentContextEvidence`, `SubAgentOutputDocument`, `SubAgentTranscript`, and `SubAgentTranscriptReceipt` models with canonical checksum roundtrip and stable refs. (AST-FR-001, AST-FR-004, AST-FR-006)
- [ ] 1.3 Define `SubAgentTranscriptStorePort`, typed query semantics, stable persistence errors, size limits, and immutable/idempotent write contract. (AST-FR-002, AST-FR-008, AST-FR-011)
- [ ] 1.4 Upgrade `FakeSubAgentTranscriptStore` to implement the production port semantics while remaining an explicitly injected test-only store. (AST-FR-002, AST-FR-008)
- [ ] 1.5 Add contract tests for schema/checksum roundtrip, identity derivation, malformed refs, same/same idempotency, same/different conflict, and legacy-unavailable diagnostics. (AST-FR-001..004, AST-FR-008, AST-FR-012)

## 2. Durable Run-Scoped Adapter

- [ ] 2.1 Implement an atomic create-if-absent filesystem primitive with path/reparse validation, flush/fsync, immutable conflict behavior, and Windows/Linux contract coverage. (AST-FR-008, AST-FR-011)
- [ ] 2.2 Implement `FilesystemSubAgentTranscriptStore` in `infrastructure/storage/harness` using one run-scoped immutable context/output/transcript/receipt bundle. (AST-FR-002, AST-FR-006, AST-FR-011)
- [ ] 2.3 Implement restart-safe read/verify, bounded parent query, deterministic attempt lookup, path/schema/size/checksum validation, and typed corruption diagnostics. (AST-FR-003, AST-FR-006, AST-FR-011)
- [ ] 2.4 Add adapter tests for reopen, no dangling body/index state, two-instance/thread/process concurrency, tamper, missing body, size bounds, query scope/order/deduplication, and unavailable storage. (AST-FR-007, AST-FR-008, AST-FR-010, AST-FR-011)

## 3. Runtime Durability Gate And Recovery

- [ ] 3.1 Require explicit `SubAgentTranscriptStorePort` injection in `SubAgentRuntime` and keep fake construction only in `FakeSubAgentRuntime` and explicit tests. (AST-FR-002)
- [ ] 3.2 Build allowlisted bounded context/output/transcript documents for successful, failed, and halted attempts without synthetic refs or duplicate full output. (AST-FR-004, AST-FR-006, AST-FR-010)
- [ ] 3.3 Replace truthy-ref transcript gating with receipt/body/output read-back, checksum, and invocation identity verification. (AST-FR-003, AST-FR-006)
- [ ] 3.4 Add a read-only committed-outcome recovery path that reuses the exact receipt before any live worker call and emits sanitized stable observations. (AST-FR-007, AST-FR-009)
- [ ] 3.5 Add adversarial runtime tests for nested private keys, secret-like values, oversize bodies, fabricated/stale receipts, store failures, and zero-worker recovery reuse. (AST-FR-003, AST-FR-007, AST-FR-009, AST-FR-010)

## 4. TaskPlan Result And Event Lineage

- [ ] 4.1 Add typed immutable worker evidence and propagate complete task/attempt identity plus receipt evidence through `ResolvedSubAgentTaskAdapter`. (AST-FR-004, AST-FR-005)
- [ ] 4.2 Introduce versioned `TaskResultRecord` v2 transcript/output evidence fields and a checksum-preserving unversioned-v1 reader with explicit legacy-unavailable behavior. (AST-FR-005, AST-FR-012)
- [ ] 4.3 Require the TaskPlan verifier to detect subagent bindings, verify receipt/output through the store, and use the durable candidate-output ref as successful `result_ref`. (AST-FR-003, AST-FR-005, AST-FR-006)
- [ ] 4.4 Persist transcript/output evidence in accepted, rejected, completed, and failed TaskPlan events and validate it during durable store reconciliation. (AST-FR-005, AST-FR-007)
- [ ] 4.5 Verify transcript/output evidence during replay/checkpoint/recovery and add receipt-to-TaskResult crash recovery without live worker/tool/memory/publication calls. (AST-FR-007, AST-FR-009, AST-FR-012)
- [ ] 4.6 Add TaskPlan tests for success/failure lineage, non-subagent optionality, event/record mismatch, v1 fixture migration, crash matrix reconciliation, tamper rejection, and zero-live-call replay. (AST-FR-005..009, AST-FR-012)

## 5. Research Production Composition

- [ ] 5.1 Explicitly construct the durable transcript adapter under the configured Research artifact root and inject the same verifier into SubAgentRuntime and TaskPlan result/replay boundaries. (AST-FR-002, AST-FR-003, AST-FR-011)
- [ ] 5.2 Replace diagnostics-only transcript wiring with typed worker evidence and prove structure/contribution/experiments attempts have readable output/transcript lineage. (AST-FR-005, AST-FR-006)
- [ ] 5.3 Add production-like Research integration tests for restart resolution, unavailable-store fail-closed behavior, post-receipt crash reuse, and offline replay call counts. (AST-FR-007, AST-FR-009, AST-FR-011)
- [ ] 5.4 Add architecture/source checks that production has no implicit fake transcript store and interfaces do not directly expose the transcript store. (AST-FR-002, AST-FR-010)

## 6. Verification And Evidence

- [ ] 6.1 Run contract, adapter, subagent, TaskPlan, Research integration, and composition tests and record requirement-level evidence in `evidence.md`.
- [ ] 6.2 Run `./.venv/Scripts/python.exe -m scripts.dev compile` and fix all source/contract errors.
- [ ] 6.3 Run `./.venv/Scripts/python.exe -m scripts.dev smoke` and fix all mandatory gate failures.
- [ ] 6.4 Run `openspec validate harness-durable-subagent-transcript --strict` and `openspec validate --all --strict`, then confirm every AST-FR requirement has implementation, passing test, and commit evidence.
