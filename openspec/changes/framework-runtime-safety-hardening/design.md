## Context

The current worker reclaim path treats Redis consumer-group idle time as an execution lease. A handler that runs longer than `reclaim_stale_ms` receives no per-task renewal, so another worker can `XCLAIM` and execute the same stream entry while the original handler is still active. Completion is a plain `XACK`, attempt state exists only on a deserialized object, and the original owner can acknowledge after ownership moved.

Tool and Workflow timeout paths have the same ownership flaw in process: they return after `join(timeout)` or `future.cancel()`, although Python cannot cancel an already running thread. Retry starts immediately, and Workflow attempts write through the same scoped buffer. The remaining audit defects are boundary failures: a duplicate worker `Task` model, duplicate tool ownership, missing generic HTTP envelope handling, and raw exception projection through MCP/stdio and Redis DLQ records.

The change must preserve existing typed public errors, framework/business/infrastructure dependency direction, synchronous handler compatibility, and Redis Streams deployment. It must not pretend that Redis ACK or Python thread cancellation provides exactly-once external effects.

## Goals / Non-Goals

**Goals:**

- Prevent a healthy long-running Redis task from being reclaimed and prevent stale owners from completing queue state after ownership changes.
- Persist monotonic attempt and fencing state independently of immutable stream payloads.
- Ensure timeout retry never overlaps an unconfirmed Tool or Workflow attempt.
- Prevent timed-out Workflow attempts from committing late buffer mutations.
- Preserve approved typed failures while removing unknown exception text from public or durable diagnostic boundaries.
- Converge worker delegation and tool registration on one canonical owner.

**Non-Goals:**

- Claiming exactly-once behavior for arbitrary external APIs, LLMs, tools, or databases.
- Forcibly killing arbitrary in-process Python callables or introducing a general remote execution service.
- Replacing Redis Streams, the worker scheduler, or the active durable-event runtime design.
- Changing successful API/MCP/CLI payloads or weakening existing artifact integrity error types.

## Decisions

### 1. Redis task ownership uses a separate fenced lease ledger

Each leased stream entry receives a Redis hash keyed by queue/group/message identity. The ledger stores `task_id`, `owner`, a random `lease_id`, monotonically increasing `fencing_token`, monotonically increasing `attempt`, server-time expiry, and state. New delivery and reclaim establish this state through Lua scripts. Reclaim is allowed only after the ledger expiry; PEL idle time remains a candidate scan signal, not the ownership authority.

Workers renew the lease at an interval below one third of the TTL while the handler is active. `renew`, success completion, retry transition, and dead-letter transition compare owner, lease id, and fencing token in Lua. A stale operation raises a typed `StaleTaskLeaseError` and cannot `XACK`, enqueue a replacement, or write DLQ state. Retry/DLQ scripts atomically create the next record and acknowledge the old stream entry.

The canonical `LeasedTask` carries immutable lease identity. Its `Task.attempts` value comes from the lease ledger rather than the original stream JSON. A stable `task_id`-derived effect key and fencing token are exposed to handlers through task execution metadata so idempotent sinks can reject repeated or stale effects.

Alternatives rejected: `XAUTOCLAIM` still uses idle time and does not fence a late owner; worker-registry heartbeat is process-wide rather than task ownership; an owner check followed by a separate `XACK` has a race.

### 2. Timeout is a supervised state transition, not thread abandonment

A shared `AttemptSupervisor` creates an `AttemptContext` containing attempt id, deadline, cancellation event, stable idempotency key, and fencing generation. On deadline it signals cancellation and waits the configured cancellation grace interval. A retry is eligible only after the prior thread has terminated and the operation is read-only or explicitly idempotent. If termination is not confirmed, or an external/irreversible operation has an uncertain outcome, the result is typed `INDETERMINATE`/unconfirmed timeout and automatic retry stops.

The supervisor exposes the current context through an immutable context-local accessor, allowing cooperative tools/runners/transports to check cancellation without changing every callable signature at once. Registered components may add an explicit context parameter in later migrations. MCP transports retain their native deadline but receive the same idempotency/cancellation metadata when supported.

Alternatives rejected: `Future.cancel()` cannot stop a running thread; immediate retry repeats effects; blocking forever to join defeats bounded execution; process termination is not a safe generic answer for non-pickleable callables or effects already accepted by an external system.

### 3. Workflow attempts stage buffer writes before commit

Every step attempt gets an overlay view. Reads use a snapshot of the permitted base values; writes, deletes, lineage, and schema checks remain local to the overlay. Only the currently fenced successful attempt can atomically apply the staged mutations to the base `DataBuffer`. Timeout or cancellation closes the overlay, and late writes raise `StaleWorkflowAttemptError` without changing base state.

Workflow timeout status remains distinct from generic failure. `ToolStatus.TIMEOUT` projects to `StepStatus.TIMEOUT`. Retry policy additionally checks the runner side-effect capability and supervisor termination state, so Tool-level and Step-level retries cannot multiply an uncertain attempt.

### 4. Unknown errors use one safe public projection

An allow-listed classifier preserves stable, already-public typed errors such as validation/not-found errors and artifact integrity failures. Unknown exceptions become a fixed public type/message (`MCPInternalError` / `internal error`, or the corresponding worker internal failure) plus a generated correlation `error_id`; raw exception text is available only to server-side structured logging.

HTTP request id is stored both in the context variable and `request.state`. A generic exception handler returns the canonical JSON error envelope, and the header, top-level body, nested error, and audit record all use that same id. The stdio and HTTP MCP adapters perform final defense-in-depth projection even if an application-service result is malformed.

Redis DLQ serialization applies the safe projection after assembling the entire record. It never persists the original reason, exception string, traceback, task secret values, or event payload copy. Typed safe fields and `error_id` survive list/requeue round trips.

Alternatives rejected: regex-only redaction misses arbitrary sensitive business text; returning exception class names exposes implementation details; fixing only callers leaves direct DLQ/MCP entrypoints unsafe.

### 5. Canonical models and composition have one owner

`control.delegate_to_subagent` imports `framework.workers.models.Task` and `DEFAULT_TASK_QUEUE`; the legacy `framework.tool.builtin.Task` export resolves to that class. A real queue-to-worker regression proves execution rather than only serialization.

`web.search` is owned by `infrastructure.tools`. Business composition forwards the configured provider into the infrastructure builder and does not register the same tool again. Registry duplicate rejection remains fail-closed; the fix removes duplicate ownership instead of skipping conflicts.

## Risks / Trade-offs

- [A Redis connectivity loss can make an external effect outcome uncertain] -> cancel cooperatively, reject stale terminal queue operations, pass stable idempotency/fencing data, and report indeterminate instead of retrying blindly.
- [Lua behavior differs across Redis clients and test doubles] -> keep scripts small, version their keys/return contract, run deterministic fake conformance plus an optional real Redis integration matrix.
- [Cancellation grace increases observed timeout latency] -> make it bounded and explicit in policy/diagnostics; it is preferable to overlapping attempts.
- [Existing custom runners write before returning] -> the overlay preserves the same view API while delaying only base-buffer publication.
- [Sanitization could hide actionable domain errors] -> preserve an explicit safe-type allowlist and log unknown exceptions with `error_id` server-side.
- [Changing task lease serialization affects older pending entries] -> lazily create a v1 lease ledger when a legacy PEL entry is first observed and retain stable task/message identity.

## Migration Plan

1. Add canonical lease/attempt models, safe-error projection, and regression fixtures without changing default execution.
2. Cut Redis lease, renew, completion, retry, and DLQ paths to fenced scripts; support legacy pending entries by initializing ledger state on claim.
3. Enable worker renewal around handler execution and expose idempotency/fencing context.
4. Cut Tool and Workflow timeouts to the shared supervisor and Workflow buffer overlays; keep unconfigured grace behavior backward-compatible but never overlap retries.
5. Switch HTTP/MCP/stdio/DLQ boundaries and canonical Tool/Task composition.
6. Run focused concurrency and security tests, mandatory smoke, strict OpenSpec validation, and a rollback drill.

Rollback must not restore blind `XCLAIM` or overlapping timeout retries. If the new Redis lease path cannot initialize, workers fail closed before executing a claimed task; operators may disable reclaim while preserving pending entries. Interface projection can roll back independently only if unknown exception messages remain sanitized.

## Open Questions

None for implementation start. Process-isolated execution and sink-specific fencing enforcement are follow-up capabilities; this change exposes the required context and prevents automatic overlap in the current in-process runtime.
