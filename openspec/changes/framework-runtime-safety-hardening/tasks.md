## 1. Failing Regressions And Contracts

- [x] 1.1 Add Tool timeout regressions proving an unconfirmed attempt cannot overlap a retry and a late side effect occurs at most once.
- [x] 1.2 Add Workflow timeout regressions proving a timed-out attempt cannot publish late buffer writes and external-write steps do not retry uncertain outcomes.
- [x] 1.3 Add Redis lease/reclaim regressions for active renewal, expired reclaim, stale-owner completion rejection, monotonic attempts, and terminal transition idempotence.
- [x] 1.4 Add delegate-to-worker integration proving the canonical worker `Task` reaches an `InMemoryTaskQueue` handler.
- [x] 1.5 Add HTTP, MCP tool/resource/prompt, HTTP MCP, and stdio regressions for safe unknown errors and one request id across wire and audit boundaries.
- [x] 1.6 Add Redis DLQ regressions proving nested exception text and task secrets are absent while safe typed fields round-trip.
- [x] 1.7 Add service and CLI regressions proving dangerous Tool list/schema composition contains unique names and one `web.search` with custom-provider forwarding.

## 2. Shared Attempt Supervision

- [x] 2.1 Add immutable `AttemptContext`, cooperative cancellation, stable logical idempotency key, fencing generation, and context-local access under a framework-owned shared module.
- [x] 2.2 Implement `AttemptSupervisor` deadline, cancellation grace, confirmed termination, unconfirmed timeout, and bounded diagnostic semantics.
- [x] 2.3 Extend Tool timeout errors/results with safe termination and indeterminate metadata without exposing executor exception contents.
- [x] 2.4 Cut Tool retry execution to the supervisor and forbid timeout retry for unconfirmed or non-idempotent external attempts while preserving the shared total-attempt budget.
- [x] 2.5 Adapt outbound MCP timeout handling to the same cancellation/idempotency contract and never treat `future.cancel()` as confirmed termination.

## 3. Workflow Attempt Isolation

- [x] 3.1 Add a schema-validating attempt buffer overlay that snapshots reads, stages writes/deletes/lineage, commits only the current fence, and rejects late writes after close.
- [x] 3.2 Cut `StepInvoker` to `AttemptSupervisor`, attempt overlays, cancellation grace policy, and safe side-effect-aware retry decisions.
- [x] 3.3 Preserve `ToolStatus.TIMEOUT` as `StepStatus.TIMEOUT` with termination metadata in `ToolCallStepRunner`.
- [x] 3.4 Ensure nested Tool and Step policies share a total attempt budget and stable logical idempotency key.
- [x] 3.5 Add cancellation checks at owned built-in runner boundaries and prove parallel/subworkflow late attempts cannot mutate parent buffer state.

## 4. Fenced Redis Worker Leases

- [x] 4.1 Extend canonical `LeasedTask` and worker errors with lease id, fencing token, authoritative attempt, expiry, stable effect key, and typed stale-lease semantics.
- [x] 4.2 Implement versioned Redis lease keys and Lua scripts for initial lease, renew, expired reclaim, guarded ACK, guarded retry, and guarded DLQ transition using Redis server time.
- [x] 4.3 Make initial delivery and legacy pending-entry adoption persist monotonic attempts independently of stream task JSON.
- [x] 4.4 Run a bounded lease renewer while a handler executes and cancel the handler attempt context when renewal loses ownership.
- [x] 4.5 Refactor worker success/failure paths to use guarded atomic terminal queue operations and reject stale owners without a second ACK/enqueue/DLQ write.
- [x] 4.6 Expose effect idempotency and fencing context to production memory/source handlers and keep existing handler call compatibility.
- [x] 4.7 Add fake-Redis script conformance and optional real-Redis concurrent worker coverage for active renewal, crash reclaim, and late completion.

## 5. Canonical Tool And Worker Composition

- [x] 5.1 Remove the duplicate Tool-local `Task`, import the canonical worker model/default queue, and preserve the compatibility export identity.
- [x] 5.2 Give `web.search` one infrastructure owner and forward the business custom provider without duplicate registration.
- [x] 5.3 Verify safe/dangerous business and infrastructure registries retain their intended tools, approval metadata, and duplicate fail-closed behavior.

## 6. Safe Error Boundaries

- [x] 6.1 Add a dependency-safe public error projector with explicit approved types, fixed unknown messages, bounded error ids, and structured server logging hooks.
- [x] 6.2 Apply safe projection to MCP prompt, resource, and tool results while preserving artifact integrity, validation, and not-found contracts.
- [x] 6.3 Apply defense-in-depth safe projection to stdio JSON-RPC and HTTP MCP adapters.
- [x] 6.4 Persist canonical request id on request state, add generic HTTP exception handling, and align response header/body/nested error/audit ids.
- [x] 6.5 Apply final whole-record safety projection to Redis DLQ reason/error/event serialization and safe list/requeue round trips.
- [x] 6.6 Ensure worker handler exceptions produce safe public/DLQ results while raw details remain server-side only.

## 7. Verification And Delivery

- [x] 7.1 Run focused Tool, Workflow buffer/runtime, worker model/queue/service, Tool CLI/service, HTTP, MCP, stdio, and Redis storage suites.
- [x] 7.2 Run deterministic concurrency/fault-injection repetitions and inspect for duplicate effects, stale ACKs, late buffer writes, secret leakage, and lingering owned attempt threads.
- [x] 7.3 Run `openspec validate framework-runtime-safety-hardening --strict`, `openspec validate --all --strict`, and `git diff --check`.
- [x] 7.4 Run `.\.venv\Scripts\python.exe -m scripts.dev compile` and mandatory `.\.venv\Scripts\python.exe -m scripts.dev smoke`; fix root causes.
- [x] 7.5 Update task evidence, commit with path-scoped staging, and confirm no unrelated active `durable-event-runtime` files are modified.
