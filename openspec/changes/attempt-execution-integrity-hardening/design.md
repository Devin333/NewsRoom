## Context

`AttemptSupervisor`, `AttemptBudget`, and `AttemptContext` provide a common execution envelope used by Workflow, ToolRuntime, parallel branches, and workers. The existing implementation prevents a confirmed timeout from overlapping its immediate retry, but several identities are currently conflated:

- a budget claim number is treated as though it were a resource-issued fencing token;
- a parent logical-operation key is reused directly by sibling Tool calls;
- a bounded retry count is treated as though it also bounds live timed-out threads;
- a successful branch return is treated as publishable even when a sibling or descendant remains unconfirmed.

The design must preserve the Harness boundary: deterministic runtime code owns retry authorization, budget admission, write ownership, and publication. Workers and LLM-produced content cannot relax these decisions.

## Goals / Non-Goals

**Goals:**

- Make retry safety fail closed for every failure mode that can hide a completed external side effect.
- Give every logical child operation a stable and collision-resistant identity while sharing the parent's fixed budget.
- Make the write resource, not the caller, issue and validate fencing ownership.
- Put a hard upper bound on live attempt threads even when user code ignores cancellation.
- Reject normal commits and artifact publication when any descendant result is indeterminate.
- Preserve deterministic telemetry sufficient to distinguish budget exhaustion, capacity exhaustion, stale ownership, and operation failure.

**Non-Goals:**

- Forcefully terminating Python threads.
- Providing exactly-once semantics for arbitrary external systems.
- Automatically inferring whether an external API supports idempotency or reconciliation.
- Replacing the existing Harness `PLAN -> EXECUTE -> VERIFY` state machine.

## Decisions

### Retry authorization is one fail-closed predicate

Timeouts and ordinary exceptions use the same side-effect rule. `NONE` and `READ_ONLY` operations may retry within budget. An operation that can write external state may retry only when its definition declares both an idempotency contract and reconciliation support. An external-write failure without that contract is terminal and indeterminate because the runtime cannot know whether the remote effect committed before the exception.

A Tool definition may separately declare `no_effect_error_types` for deterministic precondition failures proven to occur before any side effect. Those failures retain their original error type, terminate without retry, and are not marked indeterminate. The runtime does not infer this safety from broad exception families such as `ValueError`.

This is stricter than retrying all ordinary exceptions, but the alternative can duplicate external writes. The runtime will expose a typed indeterminate result rather than silently relabeling it as an ordinary failure.

### Logical identity is hierarchical; retry identity is stable

Each child operation derives its idempotency key from the parent key plus the child kind and stable child identifier. Two sibling Tool calls or parallel branches therefore receive different keys. All attempts of one child reuse that same derived key while receiving distinct attempt IDs.

The derivation is centralized in `framework.shared.attempts` and uses a bounded digest so arbitrary identifiers cannot create unbounded telemetry or storage keys.

### Budget claims and write fences are separate authorities

`AttemptBudget` issues execution permits only. It has a fixed ceiling selected before execution starts and is shared by Workflow attempts and their nested branch/Tool attempts. Nested runtimes may consume remaining permits but cannot expand the ceiling.

`DataBuffer` independently issues a monotonically increasing write lease for each step. The lease binds a generation to a unique attempt owner. An overlay can write or commit only while both generation and owner match the buffer's current lease. Callers cannot submit a preferred fencing number.

This keeps an in-memory resource safe against concurrent controllers in the same process. Durable stores remain responsible for issuing an equivalent transactional fence at their own persistence boundary.

### Live attempt work uses bounded capacity

`AttemptSupervisor` acquires a shared execution slot before creating a thread and releases it only when the thread actually exits. If all slots are occupied, a new attempt fails closed with a typed capacity-exhausted error; it does not create another thread. The capacity object is injectable for deterministic tests and has a conservative process-wide default.

A thread pool was rejected because non-cooperative tasks would permanently occupy workers while an unbounded submission queue could still grow. A semaphore directly bounds the resource that matters: live attempt threads.

### Indeterminate descendants cannot cross commit or publication boundaries

Descendant timeout state propagates through `AttemptContext`. Workflow overlays are rolled back unless the owning attempt remains current and determinate. Parallel runners check determinacy before publishing branch artifacts, and ordinary success paths cannot turn an unconfirmed descendant into a publishable result.

Diagnostic timeout metadata remains available through events and error envelopes; it is not published as a normal business artifact.

### Worker contexts start the same fixed budget

Worker task metadata supplies an explicit total-attempt ceiling when nested retries are intended. Otherwise the worker starts with a one-permit budget. This prevents worker retry policy, step retry policy, branch retry policy, and Tool retry policy from multiplying independently.

## Risks / Trade-offs

- [Previously implicit external-write retries stop] -> Return an explicit indeterminate error and require definitions to declare idempotency plus reconciliation before retry is enabled.
- [A process can temporarily exhaust attempt capacity after many non-cooperative timeouts] -> Fail new work closed, expose capacity metrics, and recover slots only when the underlying functions exit.
- [A stricter shared budget can reduce nested retries] -> Make the total ceiling explicit at the outer execution boundary and report budget exhaustion separately from operation failure.
- [In-memory fencing does not coordinate multiple processes] -> Keep `DataBuffer` ownership local and require durable adapters to issue transactional fences at the durable resource boundary.

## Migration Plan

1. Add regression tests that reproduce duplicate external effects, sibling-key collisions, stale overlay commits, budget multiplication, indeterminate artifact publication, and unbounded thread creation.
2. Introduce shared identity derivation, fixed budgets, and bounded execution capacity.
3. Change `DataBuffer.begin_attempt` to issue owner-bound leases and update the sole Workflow caller and direct tests.
4. Apply the common retry predicate to ToolRuntime and Workflow outcomes.
5. Propagate shared budgets from worker and branch contexts and guard artifact publication.
6. Run targeted tests, framework tests, compile, smoke, and strict OpenSpec validation.

Rollback is a single code-and-spec revert. There is no persisted schema migration.

## Open Questions

None. Durable multi-process fencing remains an adapter responsibility and is intentionally outside this in-memory runtime change.
