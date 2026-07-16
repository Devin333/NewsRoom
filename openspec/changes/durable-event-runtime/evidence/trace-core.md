# W3C Trace Core Evidence

Date: 2026-07-16

OpenSpec tasks: 7.1, 7.2, 7.3, 7.4, and 7.5

## Implemented contracts

- Newly generated trace and span identifiers are nonzero W3C-compatible hexadecimal values. Explicit historical identifiers remain readable but invalid legacy context is never injected into an outbound carrier.
- `TraceContext.root()`, `child()`, `to_dict()`, `from_dict()`, and `trace_fields()` remain available and propagate Agent, Tool, Memory, and Artifact business identifiers through immutable canonical snapshots.
- Redaction uses exact normalized credential fields plus schema-defined paths. It does not use substring matching, so ordinary keys that merely contain words such as `token` are preserved while registered credential forms are redacted.
- The shared propagation core bounds carrier items, traceparent, tracestate, and baggage; applies allowlists; supports restart or reject trust policies; and emits only bounded diagnostic reason classes.
- The OpenTelemetry API conversion boundary is lazy and optional. The no-op adapter preserves runtime behavior when the dependency or exporter is unavailable.
- HTTP and MCP inbound, ToolRuntime MCP/HTTP outbound, worker/message, subagent handoff, and durable delivery boundaries share bounded `extract -> child -> inject` behavior. Duplicate or malformed carriers restart or reject according to policy and never supply business authorization fields.
- Service/process identity is carried by `TelemetryResource`, component/library identity by `TelemetryInstrumentationScope`, and batch, queue, retry, redelivery, and handoff causality by bounded span links.
- Telemetry backend, tracer, span, sampler, and exporter failures are isolated from durable event and workflow behavior. Attribute policies reject raw/multiline/unbounded values, and metrics exclude tenant, user, run, event, and trace identifiers as labels.

## Verification results

```text
framework event and trace contract tests: 489 passed
Agent, Tool, Memory, and Workflow trace compatibility tests: 43 passed
framework.events import without optional telemetry setup: passed
git diff --check: passed
```

## Boundary hardening verification

```text
trace/telemetry core snapshot: 99 passed
HTTP/MCP/Tool/worker/delivery boundary snapshot: 119 passed
API/MCP/Tool/worker compatibility snapshot: 124 passed
isolated pre-commit smoke: 1006 passed, 23 skipped
source validation: is_valid=true, error_count=0, warning_count=0
```

Both commits were validated from staged patches applied to clean detached worktrees. The snapshots exclude unrelated attempt supervision, public-error, Redis lease/fencing, and Research worktree changes.
