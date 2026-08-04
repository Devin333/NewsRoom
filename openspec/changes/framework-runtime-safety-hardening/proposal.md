## Why

The framework audit reproduced overlapping execution after Redis reclaim and Tool/Workflow timeouts, plus broken worker delegation and unsafe public error handling. These defects can duplicate irreversible effects, strand delegated work, leak exception contents, and make production discovery/API surfaces fail before useful work begins.

## What Changes

- Replace idle-only Redis reclaim with renewable per-task leases, monotonic fencing tokens, owner-checked terminal operations, and persisted attempt state.
- Prevent Tool and Workflow timeout retries from overlapping an attempt that has not confirmed termination; propagate cancellation and idempotency context and halt with an indeterminate outcome when termination cannot be proved.
- Make `control.delegate_to_subagent` enqueue the canonical worker `Task` model and prove the delegated task reaches a real worker handler.
- Return a unified, request-id-consistent JSON envelope for unhandled HTTP failures and sanitize unknown MCP, stdio, and worker/DLQ failures at the final wire/storage boundary.
- Give each built-in tool one registration owner so dangerous catalog discovery and schema export contain one `web.search` definition and remain conflict-free.
- Preserve existing typed artifact, validation, not-found, and domain error contracts while sanitizing only unknown internal failures.

## Capabilities

### New Capabilities

- `attempt-execution-safety`: Defines cancellation, termination confirmation, fencing, idempotency, and non-overlapping retry behavior for Tool and Workflow attempts.
- `tool-runtime-composition-safety`: Defines canonical worker task delegation and unique built-in tool registration across framework, business, and infrastructure composition.
- `runtime-error-sanitization`: Defines safe unknown-error projection for MCP/stdio and durable worker failure records without weakening approved typed errors.

### Modified Capabilities

- `worker-scheduler-final-target-closure`: Strengthens worker leases with renewal, fencing, monotonic attempts, stale-owner rejection, and safe dead-letter persistence.
- `interfaces-contracts`: Extends the stable API error envelope and request-id invariant to unhandled internal failures and their audit records.

## Impact

- Framework: Tool timeout execution, Workflow step invocation, worker task/lease models, control tools, and tool registry composition.
- Infrastructure: Redis Streams lease state, atomic scripts, claim/renew/complete/fail behavior, and dead-letter serialization.
- Interfaces: worker execution lifecycle, HTTP middleware/exception handling, MCP service/stdio projection, and Tool CLI discovery.
- Business composition: built-in tool ownership and worker handler idempotency context.
- Tests: deterministic concurrency, timeout late-write, real/fake Redis adapter conformance, delegate-to-worker integration, HTTP/MCP/stdio error secrecy, DLQ round trips, and dangerous tool catalog uniqueness.
