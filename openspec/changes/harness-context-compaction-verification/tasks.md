## 1. Versioned Semantic Models

- [x] 1.1 Add strict enums and immutable `ContextGroupMember`, `ContextGroup`, protection-reason, reconstruction-policy, and tool-transaction state models with versioned `to_dict()` / `from_dict()`.
- [x] 1.2 Add immutable `ContextCompactionPolicy` with trusted action order, recent-tail/evidence rules, failure policy, and validated action/summary/replan/token/cost/turn bounds.
- [x] 1.3 Add immutable `ContextCompactionAction`, `ContextCompactionPlan`, action-result, loss-report, and typed outcome models with checksum-derived identity.
- [x] 1.4 Add strict `ContextSummaryClaim` and `ContextSummaryCandidate` models covering group/source support, omissions, unresolved questions, tool outcomes, loss risk, artifact ref, and worker/model/schema revisions.
- [x] 1.5 Add versioned source/result snapshot and `ContextCompressionRecord` models binding plan/actions/counts/groups/refs/gates/verdict/profile revisions without embedding sensitive bodies.
- [x] 1.6 Export new contracts through `framework.harness.context` and `framework.harness` while retaining explicit legacy-read types.

## 2. Group Materialization and Structural Validation

- [x] 2.1 Implement a deterministic segment/message/evidence/tool materializer that emits ordered group/member refs and stable identities from immutable source inputs.
- [x] 2.2 Implement role/order/output-contract validation and reject unsupported or ambiguous source shapes before planning.
- [x] 2.3 Implement tool-call/result transaction pairing, completion state, atomic membership, and pending/unresolved protection.
- [x] 2.4 Resolve trusted protection reasons for system/safety/current-task/output-contract/retry-state/evidence/control-decision groups and reject request metadata overrides.
- [x] 2.5 Materialize evidence groups with evidence/source/span/lineage/required-citation/query/conflict fields and stable loss-tracking identities.
- [x] 2.6 Add migration adapters from existing six `ContextSegment` values without treating summary strings as ordered raw message history.

## 3. Policy and Deterministic Planning

- [x] 3.1 Implement strict composition parsing for compaction policy and fail fast on unknown/unregistered actions or invalid bounds.
- [x] 3.2 Implement the deterministic planner over source snapshot, task/query binding, protection state, initial physical admission, and policy revision.
- [x] 3.3 Enforce reversible-before-lossy action ordering and stable plan ids for equivalent inputs.
- [x] 3.4 Reject plans that target partial tool transactions, protected groups, stale source snapshots, unauthorized tools, or out-of-policy actions.
- [x] 3.5 Return typed no-plan/protected-context/action-budget outcomes without unbounded internal replanning.

## 4. Typed Action Execution

- [x] 4.1 Implement `DROP_RECONSTRUCTABLE_GROUP` with complete-group removal and durable reconstruction refs.
- [x] 4.2 Implement `REPLACE_WITH_REFERENCE` using a real injected artifact/reference port and checksum-bound refs rather than fabricated URIs.
- [x] 4.3 Implement `REDUCE_AUTHORIZED_TOOL_SET` against existing trusted authorization and pending-transaction constraints.
- [x] 4.4 Implement query-bound `SELECT_EVIDENCE_SPANS` with required citation/lineage/conflict preservation and explicit omitted-span loss reporting.
- [x] 4.5 Implement `COMPACT_OLD_CONVERSATION` over complete turns/transactions while preserving the policy-defined recent complete tail.
- [x] 4.6 Implement `SUMMARIZE_GROUPS` as a bounded candidate-producing action that never mutates the active snapshot before verification.
- [x] 4.7 Implement the bounded action executor with action/summary/replan/token/cost/turn accounting and immutable action results.

## 5. Summary Candidate Ports and Gates

- [x] 5.1 Define replaceable summary-worker and summary-artifact ports plus deterministic fakes; do not install an implicit production LLM client.
- [x] 5.2 Validate candidate schema and reject free-text-only or authority-bearing worker outputs.
- [x] 5.3 Verify every candidate group/source/evidence/span/artifact/tool-outcome ref against the source snapshot and current authorization.
- [x] 5.4 Verify claim support, required evidence/citation coverage, protected facts, conflicts, omission declarations, recent tail, and policy-bounded loss risk.
- [x] 5.5 Prove rejected candidates leave source/result activation unchanged and cannot emit verified events or recursively call the summary worker.

## 6. Aggregate Post-Compaction VERIFY

- [x] 6.1 Define the `ContextPhysicalAdmissionVerifier` port and bounded prepared-evidence result without importing provider/tokenizer implementation into semantic Harness logic.
- [x] 6.2 Implement the Change 1 adapter that prepares the exact result materialization for a resolved deployment/profile and returns fingerprint/count/budget/admission revisions.
- [x] 6.3 Implement versioned structure, protection, tool-transaction, provenance, evidence/loss, action-budget, snapshot-integrity, and physical-admission gates.
- [x] 6.4 Implement aggregate verdict evidence that binds every gate to the same source/result snapshots and rejects legacy boolean-only gates.
- [x] 6.5 Prohibit result promotion and provider dispatch when legacy estimates fit but prepared physical admission fails.

## 7. Bounded Runtime and Assembler Integration

- [x] 7.1 Implement `ContextCompactionRuntime` state transitions from source snapshot through plan/apply/materialize/verify/commit-or-reject with typed outcomes.
- [x] 7.2 Replace `ContextAssembler._compress_dynamic_tail()` string halving and unconditional verified event with the bounded runtime.
- [x] 7.3 Preserve no-compaction behavior when source physical admission already passes and record `NO_COMPACTION_REQUIRED` without fabricated records.
- [x] 7.4 Enforce `PROTECTED_CONTEXT_EXCEEDS_WINDOW`, `NO_ALLOWED_COMPACTION`, `ACTION_BUDGET_EXHAUSTED`, `SUMMARY_REJECTED`, and `POST_COMPACTION_VERIFY_FAILED` fail-closed paths.
- [x] 7.5 Ensure a verified result can authorize dispatch only after the same prepared identity and canonical durable commit remain valid.

## 8. Durable Events, Snapshots, and Replay

- [x] 8.1 Store immutable checksum-derived source/result snapshots and real artifact refs without mutating `ContextSnapshotStore.envelopes` in place.
- [x] 8.2 Project planned/action/candidate/verified/rejected facts through the existing canonical Harness event/transcript port with bounded redacted metadata.
- [x] 8.3 Make verified event append the activation commit boundary and fail closed when append fails.
- [x] 8.4 Extend transcript/replay reports with pinned plan/action/result/admission/gate evidence and `side_effects_replayed=false`.
- [x] 8.5 Verify record/snapshot/summary-artifact checksums and cross-refs during replay without invoking LLM, tools, memory writes, or publication.
- [x] 8.6 Classify old `CompressionRecord`/snapshot projections as `legacy_unverified` and prevent them from authorizing recovery or dispatch.

## 9. Research Composition and Adversarial Tests

- [x] 9.1 Inventory live Research context assembly/materialization callsites and bind the new runtime through the proper composition/application boundary.
- [x] 9.2 Add group/materialization tests for role order, required output contracts, fake profile overrides, stable ids, and immutable source refs.
- [x] 9.3 Add tool-transaction tests for orphan results, pending calls, complete atomic removal/replacement, and partial-action rejection.
- [x] 9.4 Add planner/action tests for determinism, stale plans, reversible ordering, protected-only overflow, evidence selection, tool reduction, recent-tail preservation, and every execution bound.
- [x] 9.5 Add summary tests for invented refs/outcomes, unsupported claims, missing required citations, conflicts, omission/loss policy, authority fields, and summary-call exhaustion.
- [x] 9.6 Add aggregate VERIFY tests proving second physical gate failure cannot emit verified evidence or call a provider.
- [x] 9.7 Add durability/replay corruption and crash-boundary tests for source/result/record/gate/artifact/event integrity and legacy classification.
- [x] 9.8 Add Research integration tests covering evidence-first compaction, verified summary replacement, protected-context halt, and deterministic replay.

## 10. Validation and Delivery

- [x] 10.1 Run focused Harness context/runtime/replay and Research context tests; fix root causes and retain adversarial evidence.
- [x] 10.2 Run `python -m scripts.dev compile`, the broad non-live suite appropriate to shared Harness changes, and `python -m scripts.dev smoke`.
- [x] 10.3 Run `openspec validate harness-context-compaction-verification --strict` plus relevant Change 1/cache validation where shared contracts are consumed.
- [x] 10.4 Audit dependency direction, sensitive event/record projections, actual artifact refs, bounded state transitions, and the live dirty-worktree baseline.
- [x] 10.5 Commit only this change's verified files with path-scoped staging, leaving concurrent cache/user modifications untouched.

## Validation Evidence (2026-08-11)

- Focused Harness context/runtime/replay and Research context suites: `238 passed`.
- `python -m scripts.dev compile`: passed; the compile phase also passed inside the final smoke run.
- Research broad non-live suite: `1011 passed, 2 skipped, 23 deselected, 17 failed`; all 17 failures are isolated to the concurrent `structured_output` / `candidate_worker` dirty-worktree baseline and reproduce as `structured-output capability is not configured`.
- `python -m scripts.dev smoke`: `2048 passed, 23 deselected, 1 failed`; the sole recorded-transport failure reaches the same concurrent `structured_output` capability error after context admission.
- Strict OpenSpec validation covers this change and `model-aware-llm-context-preflight`; final validation is repeated after this checklist update.
- Delivery uses path-scoped commits; concurrent `framework/llm`, `configs/models.yaml`, and `infrastructure/research/candidate_worker.py` modifications remain untouched.
