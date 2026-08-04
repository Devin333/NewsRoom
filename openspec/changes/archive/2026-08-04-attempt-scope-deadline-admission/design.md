## Context

The previous integrity hardening introduced a fixed shared `AttemptBudget`, bounded live-attempt capacity, owner-bound `DataBuffer` leases, stable nested idempotency keys, and fail-closed indeterminate propagation. That baseline is valuable but still conflates four independent questions: how many retries one logical operation may take, how many retries the root execution may authorize, which physical attempt is running, and which protected resource owns a write. Workflow and Tool runtimes also derive a child timeout with `min(local, parent_remaining)` and start work without accounting for cancellation, VERIFY, or commit reserves.

The implementation spans shared primitives, Workflow/Tool/Parallel/Worker callers, policy schemas, and durable event readers. The design therefore centralizes admission while preserving the existing cooperative-cancellation and resource-specific lease contracts.

## Goals / Non-Goals

**Goals:**

- Separate root `RetryCreditLedger`, per-operation `LocalRetryBudget`, `AttemptIdentity`, and resource-issued `ResourceWriteLease`.
- Admit only work whose effective monotonic execution window can satisfy its typed minimum start window and required reserves.
- Make admission claims atomic under concurrency and side-effect-free on rejection or rollback.
- Apply one contract across Step, Tool, ToolBatch, parallel branch, nested Worker, and standalone supervisor paths.
- Keep retry safety and `INDETERMINATE` propagation ahead of any remaining budget.
- Emit replayable, scope-aware decision and outcome fields while decoding legacy durable histories read-only.

**Non-Goals:**

- Extending a root hard deadline or adding an LLM-driven duration predictor.
- Force-killing non-cooperative Python threads or promising exactly-once external effects.
- Replacing Harness PLAN -> EXECUTE -> VERIFY, TaskPlan, quality gates, side-effect authority, or artifact integrity ownership.
- Managing first-call/tool-count, parallelism, token, cost, or artifact budgets with the retry ledger.
- Adding UI or manual deadline-editing APIs.

## Decisions

### 1. Use a root retry-credit ledger plus independent local budgets

`RetryCreditLedger` is an execution-scoped, lock-protected ceiling for retries only. A first physical attempt does not consume a credit; each admitted `local_attempt_no > 1` atomically reserves one credit and receives an opaque `retry_credit_id`. `LocalRetryBudget` belongs to one stable `operation_id`, tracks `max_attempts`, `used_attempts`, and `next_local_attempt_no`, and is never shared by siblings or inferred from nested runner structure.

The admission controller reserves the local slot and optional root credit as one transaction after all deterministic safety and deadline gates pass. A reservation object can commit at physical start or roll back both counters. Capacity is acquired before the reservation is committed, so capacity rejection cannot consume a budget.

**Alternative rejected:** keeping a shared total-attempt counter and calculating Step limits by adding nested limits. It makes local policy depend on implementation topology and cannot distinguish first calls from retries.

### 2. Make physical identity explicit and remove generic fencing authority

`AttemptContext` carries `attempt_id`, `operation_id`, stable `idempotency_key`, `local_attempt_no`, `parent_attempt_id`, effective monotonic deadline, cancellation, and optional opaque `retry_credit_id`. It does not carry or generate `fencing_token`. `DataBuffer.begin_attempt` remains the sole issuer of its resource-specific lease (`resource_id`, `lease_generation`, `owner_attempt_id`); adapters for other resources retain their own authority.

**Alternative rejected:** renaming the shared budget sequence to `attempt_no` or `fencing_token`. A name change would preserve the authority confusion and break independently nested numbering.

### 3. Centralize deterministic deadline admission

`DeadlineAdmissionPolicy` contains non-negative `timeout_seconds` (optional), `min_start_window_seconds`, `cancellation_grace_seconds`, and `completion_reserve_seconds`. Root execution limits expose a monotonic hard deadline plus VERIFY and commit reserves. `AttemptContext.deadline` is the parent's already-narrowed callable deadline, so a child uses it directly as `parent_available_until` and subtracts only the child's cancellation/completion reserve. The controller computes `requested_until = now + timeout`, `root_available_until = root_hard_deadline - verify_reserve - commit_reserve`, and `effective_until = min(requested_until, parent_available_until - child_reserve, root_available_until - child_reserve)`. A request is admitted only when the resulting execution window is at least the minimum start window. No parent reserve is deducted twice.

The controller performs deadline, cancellation, determinacy, retry safety, local slot, root credit, and capacity checks before publishing a start fact, invoking a transport, preparing an artifact, or issuing a resource lease. All calculations use an injectable monotonic clock; wall-clock timestamps are telemetry only.

**Alternative rejected:** starting immediately and relying on a child timeout to cancel later. This creates predictable late calls, side effects, and lease churn when the operation cannot meet its declared minimum window.

### 4. Make rejection and rollback typed and replayable

Admission decisions use stable reason codes such as `DEADLINE_ADMISSION_REJECTED`, `RETRY_BUDGET_EXHAUSTED`, `CAPACITY_EXHAUSTED`, `PARENT_CANCELLED`, `INDETERMINATE_DESCENDANT`, and `UNSAFE_RETRY`. A rejection emits an event with operation scope, policy/deadline calculation, and budget snapshots, but no `attempt_id`, local increment, credit, capacity occupancy, or lease. `AttemptSupervisor` is the sole lifecycle publisher: it emits `attempt_started` after the thread/start gate and reservation are ready but before resource preparation or callable release, binds the lifecycle sink into the child context for nested Tool/MCP/branch calls, and emits exactly one terminal fact for every started attempt.

If durable `attempt_started` persistence fails, the start gate remains closed and capacity/local/root reservations roll back. Once `attempt_started` succeeds, the reservation commits. A later resource preparation failure is therefore a started `FAILED` outcome and cannot be misreported as a no-start rejection. Every started path converges on one supervisor-owned sequence: caller-specific outcome finalization, exactly-once resource cleanup, and then `attempt_terminal`. Workflow commits its private DataBuffer overlay during outcome finalization; Worker stops and confirms its lease renewer during cleanup. A finalization or cleanup failure becomes `INDETERMINATE` before the terminal fact is emitted.

Lifecycle sinks are authoritative unless they explicitly opt into soft observability semantics. Workflow durable writers and injected durable Worker sinks fail closed. Tool event mirrors and Worker telemetry are soft and cannot change admission or execution results. If one authoritative sink records `attempt_started` and a later authoritative sink fails, the supervisor emits a synthetic terminal failure to sinks that may have observed the start before rolling back the unopened physical attempt.

Legacy events are decoded through a versioned read-only adapter that maps old shared permit/fence fields into diagnostic `legacy_*` fields; replay never starts live work or treats those fields as new resource authority. New writers emit only scope-aware fields.

### 5. Integrate through an operation-context factory

Workflow StepInvoker creates a child `OperationContext` per Step logical operation; Tool and ToolBatch derive stable child keys from the parent and call identity; parallel branches use branch identity; Workers create a standalone operation unless explicitly nested. Retries reuse the operation context and key while allocating a new physical attempt. Nested runners receive the parent execution limits and available deadline, never a shared mutable attempt counter or inherited fence.

The only caller-facing start path is the shared admission controller/supervisor. This prevents each runtime from implementing a subtly different claim order. A resource lease is requested only after the durable start fact commits and immediately before the actual resource-owning callable is released. Workflow supplies a durable sink and finalizes its buffer before terminal projection, Tool mirrors local ToolEvents while inheriting the Workflow sink, parallel/batch/MCP children inherit the sink through `AttemptContext`, and Worker exposes an injectable durable sink plus failure-isolated telemetry.

## Risks / Trade-offs

- [Policy migration] Existing callers may omit typed windows or expect a shared total-attempt limit -> supply explicit validated defaults and fail validation for malformed policies; preserve a read-only legacy decoder.
- [False rejection] Conservative reserves can reject work that would have completed -> expose deterministic metrics/reason codes and tune typed policy defaults, but never bypass the hard deadline.
- [Concurrency races] Multiple siblings may pass preflight together -> serialize local/root reservations and capacity acquisition in the controller, with rollback tests using barriers.
- [Schema consumers] Event readers may depend on legacy `fencing_token` -> version the event projection and retain read-only aliases only at the decoder boundary; new live events never write them.
- [Partial startup] Thread creation or durable start persistence can fail before commit -> keep the start gate closed and roll back capacity/local/root reservations. Resource preparation happens after the durable start boundary; if it fails, emit a started terminal failure and invalidate any partial resource lease through the resource owner.

## Migration Plan

1. Archive and validate the completed integrity-hardening change so its requirements are main-spec baseline.
2. Add shared primitives and event schema behind the new capability, then migrate Workflow/Tool/Parallel/Worker callers to operation contexts and admission.
3. Add old-history fixtures and offline replay checks; reject new production writes that use generic fence or shared-budget fields.
4. Run targeted concurrency/deadline/side-effect tests, compile, smoke, strict OpenSpec validation, and an architecture/source scan.
5. If admission rejection rates are unexpectedly high, tune typed defaults or roll back the policy wiring only; never restore deadline expansion, inherited fences, or unsafe retry.

## Open Questions

- Which existing durable event stream version should carry the first scope-aware projection? The implementation will use the repository's current attempt event version registry and add a monotonic version rather than alter old records.
- Should default `completion_reserve_seconds` be zero for read-only operations? The controller supports zero as an explicit validated value, while root VERIFY/commit reserves remain authoritative.
