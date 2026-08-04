## 1. Shared Scope and Admission Primitives

- [x] 1.1 Replace shared local-attempt semantics in `framework/shared/attempts.py` with `LocalRetryBudget`, root `RetryCreditLedger`, stable `OperationContext`, `AttemptIdentity`, and typed reservation/rejection models.
- [x] 1.2 Add validated `DeadlineAdmissionPolicy`, root execution limits, monotonic deadline planner, reserve arithmetic, and injectable clock support.
- [x] 1.3 Refactor `AttemptSupervisor` to centralize pre-start safety/deadline/capacity/budget admission, rollback reservations, and no-start outcomes; remove inherited permit and generic fence creation.
- [x] 1.4 Preserve bounded live capacity, cooperative cancellation, termination confirmation, descendant determinacy propagation, and fail-closed retry safety under the new contexts.
- [x] 1.5 Add shared primitive tests for arithmetic boundaries, invalid policy values, concurrent local/root claims, capacity rejection, rollback, parent cancellation, and zero ghost consumption.

## 2. Policy, Identity, and Outcome Contracts

- [x] 2.1 Add typed timeout/tool/execution policy fields for minimum start window, cancellation grace, VERIFY/commit reserves, and explicit root retry ceiling with serialization round-trip validation.
- [x] 2.2 Remove generic `fencing_token` from live attempt context, timeout/error envelopes, and new runtime diagnostics; retain resource-specific lease fields only at resource boundaries.
- [x] 2.3 Define stable admission/outcome reason codes and redacted scope-aware event payloads including deadline and budget snapshots without tool arguments or secrets.
- [x] 2.4 Add focused tests proving identity separation, stable sibling/retry keys, no generic fence production path, and outcome/reason-code serialization.

## 3. Workflow and Resource Integration

- [x] 3.1 Migrate `StepInvoker` to a Step-local retry scope and centralized admission; delete `_step_total_attempt_limit`, parent permit inheritance, and pre-admission `DataBuffer` lease acquisition.
- [x] 3.2 Ensure Workflow child deadlines reserve runner completion, deterministic VERIFY, durable outcome, and commit time while never extending root hard deadline.
- [x] 3.3 Add Workflow/DataBuffer tests for insufficient-window no-start, narrowed deadlines, stale-owner preservation, and independent Step/Tool attempt numbering.

## 4. Tool, Batch, Parallel, and Worker Integration

- [x] 4.1 Migrate Tool executor, timeout helper, and MCP adapter to explicit ToolCall operation scopes and admission; remove parent fence/permit inheritance.
- [x] 4.2 Migrate ToolBatch and parallel branch runners so siblings have independent local budgets/keys while retries use only root retry credits.
- [x] 4.3 Migrate nested and standalone Worker contexts while preserving queue/storage lease ownership outside execution retry identity.
- [x] 4.4 Add cross-layer tests covering direct/Workflow Tool, ToolBatch, parallel branch, nested Worker Tool, and standalone timeout helper matrices.
- [x] 4.5 Re-run existing side-effect, idempotency, non-cooperative timeout, late-write, and indeterminate-publication adversarial tests without weakening assertions.

## 5. Durable History and Migration

- [x] 5.1 Add versioned read-only decoder and fixtures for legacy shared budget, `max_total_attempts`, and generic `fencing_token` history; ensure offline replay cannot invoke live effects.
- [x] 5.2 Emit new scope-aware admission/attempt events without generic attempt fence or legacy dual-write fields, and document compatibility read window/removal gate.
- [x] 5.3 Add replay and source scans proving no caller-supplied DataBuffer generation, budget-to-fence path, or legacy live field remains.

## 6. Verification and Delivery

- [x] 6.1 Run focused shared/workflow/tool tests, fix root causes, and review all attempt callers.
- [x] 6.2 Run `python -m scripts.dev compile`, `python -m scripts.dev smoke`, `openspec validate attempt-scope-deadline-admission --strict`, and `git diff --check`.
- [x] 6.3 Update `framework-shared.md` and attempt runtime diagram only after runtime evidence confirms the new terminology and behavior.
- [x] 6.4 Review the full diff, stage only intended paths, and create the required implementation commit.
