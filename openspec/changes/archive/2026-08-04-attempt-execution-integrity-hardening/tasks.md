## 1. Shared Attempt Primitives

- [x] 1.1 Add hierarchical logical-operation key derivation and typed indeterminate/capacity errors in `framework/shared/attempts.py`.
- [x] 1.2 Make `AttemptBudget` a fixed-ceiling shared permit counter and add injectable bounded live-attempt capacity to `AttemptSupervisor`.
- [x] 1.3 Propagate descendant indeterminate state and prevent active-attempt checks from allowing indeterminate work to cross execution boundaries.

## 2. Retry and Identity Enforcement

- [x] 2.1 Apply the common fail-closed retry predicate to ordinary Tool failures and return an indeterminate result for unsafe external-write failures.
- [x] 2.2 Derive distinct Tool and batch-child keys while keeping one key stable across retries.
- [x] 2.3 Make Workflow step retry decisions honor indeterminate Tool outcomes and reject unsafe external-write retries.

## 3. Resource Fencing and Nested Budgets

- [x] 3.1 Change `DataBuffer` to issue owner-bound monotonic leases and reject caller-supplied fencing generations.
- [x] 3.2 Update `StepInvoker` to reserve the fixed outer budget, pass the resource-issued lease to overlays, and share it with nested runners.
- [x] 3.3 Make parallel branches and ToolBatch workers claim from the shared budget for every retry and use distinct child contexts.
- [x] 3.4 Initialize Worker service attempt contexts with an explicit fixed total budget.

## 4. Publication Integrity

- [x] 4.1 Block parallel branch artifact publication and Workflow buffer commits when any descendant is indeterminate.
- [x] 4.2 Preserve diagnostic error envelopes and durable attempt events for budget, capacity, stale-owner, and indeterminate outcomes.

## 5. Regression Coverage and Verification

- [x] 5.1 Add adversarial tests for ordinary external-write failure, sibling-key collision, stale owner fencing, budget multiplication, capacity exhaustion, and indeterminate publication.
- [x] 5.2 Run targeted framework tests and fix all regressions without weakening assertions.
- [x] 5.3 Run `python -m scripts.dev compile`, `python -m scripts.dev smoke`, and `openspec validate attempt-execution-integrity-hardening --strict`.
- [x] 5.4 Review the final diff, stage only intended paths, and create the required commit.
