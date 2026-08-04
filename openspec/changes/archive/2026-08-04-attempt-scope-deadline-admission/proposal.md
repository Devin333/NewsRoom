## Why

The current attempt runtime uses one shared `AttemptBudget` for nested Workflow, Step, Tool, branch, and Worker execution. The same permit sequence can also be exposed as a generic fencing token, so local retry policy, root retry ceilings, physical attempt identity, and resource ownership are not independently auditable. Child timeout calculation also starts work when the remaining window is already smaller than the operation's declared minimum executable window, consuming capacity, budget, and leases for work that cannot finish safely.

This change makes those boundaries explicit before more runtimes and durable event consumers depend on the ambiguous contract.

## What Changes

- **BREAKING** Replace the shared nested-attempt counter with a root-scoped `RetryCreditLedger` that counts retries only and an independent `LocalRetryBudget` for every logical operation.
- **BREAKING** Give every physical start a unique `attempt_id` and local `local_attempt_no`; remove generic `fencing_token` authority from `AttemptContext` and diagnostics.
- Add typed `DeadlineAdmissionPolicy` and deterministic admission that narrows parent deadlines, accounts for cancellation/VERIFY/commit reserves, and rejects too-small windows before any callable, transport, capacity, budget claim, or resource lease starts.
- Make admission claims transactional under concurrency, with rollback for failures before the durable start fact; rejected work must not create an `AttemptContext`, consume a retry credit, or issue a resource lease. Resource preparation begins only after `attempt_started`; outcome finalization and exactly-once resource cleanup complete before the terminal fact, and an unconfirmed cleanup becomes `INDETERMINATE`.
- Integrate the same operation scope and admission order into Workflow steps, parallel branches, Tool calls/batches, nested workers, and standalone attempt helpers.
- Preserve fail-closed retry safety, stable sibling idempotency keys, DataBuffer owner-bound leases, live execution capacity, and descendant `INDETERMINATE` propagation.
- Add stable admission/outcome events, metrics, replay fields, and a read-only decoder for legacy durable history; new live events must not emit the ambiguous legacy fields.

## Capabilities

### New Capabilities

- `attempt-deadline-admission`: Typed deadline policy, root retry-credit accounting, local operation budgets, deterministic admission gates, and scope-aware attempt identity.

### Modified Capabilities

- `attempt-execution-integrity`: Replace the shared nested budget requirement with independent local budgets plus a root retry ceiling, while retaining resource-issued fencing, capacity bounds, and fail-closed indeterminate publication rules.

## Impact

- `framework/shared/attempts.py` and the shared event/error models.
- Workflow StepInvoker, execution context, parallel and batch runners, Tool runtime/executors, and Worker service adapters.
- Timeout/tool policy and definition schemas, configuration validation, and durable attempt event/replay projections.
- Existing attempt isolation, capacity, timeout, side-effect, and publication tests, plus new fake-clock and concurrent-admission fixtures.
- The change is framework-internal and does not add a UI or an external dependency.
