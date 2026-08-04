## Why

The current nested-attempt implementation bounds retry counts but does not fully preserve execution integrity. External side effects can be retried after an ordinary exception without an idempotency guarantee, sibling calls can share one idempotency key, locally generated attempt numbers are treated as resource fencing tokens, timed-out work can leave an unbounded number of live threads, and indeterminate parallel work can publish artifacts before its parent rejects the result.

These gaps mean a run can stay numerically bounded while still duplicating writes, accepting stale commits, exhausting process capacity, or exposing output whose producing attempt is not known to have terminated.

## What Changes

- Define a single fail-closed retry-safety rule for timeouts and ordinary failures: external side effects are retryable only when an explicit idempotency and reconciliation contract is present.
- Derive stable, distinct idempotency keys for nested and sibling operations while preserving one key across retries of the same logical operation.
- Separate retry-budget generations from resource-issued fencing tokens and make `DataBuffer` issue monotonic, owner-bound write leases.
- Bound live attempt threads with shared execution capacity so non-cooperative timed-out work cannot grow process resources without limit.
- Make nested workflow, parallel-branch, tool, and worker attempts consume one shared, fixed total budget.
- Prevent indeterminate descendants from publishing normal artifacts or committing staged workflow data.
- Add adversarial regression tests for duplicated side effects, sibling key collisions, stale writers, nested budget multiplication, indeterminate publication, and thread-capacity exhaustion.

## Capabilities

### New Capabilities

- `attempt-execution-integrity`: Defines retry authorization, logical-operation identity, resource-issued fencing, shared nested budgets, bounded execution capacity, and publication rules for indeterminate attempts.

### Modified Capabilities

None.

## Impact

- Runtime code under `framework/shared/attempts.py`, `framework/tool/runtime/`, and `framework/workflow/runtime/`.
- Worker attempt-context construction under `interfaces/services/worker_service.py`.
- Workflow buffer ownership and artifact publication behavior.
- Targeted framework and interface tests; unsafe implicit retries will become explicit terminal indeterminate failures.
