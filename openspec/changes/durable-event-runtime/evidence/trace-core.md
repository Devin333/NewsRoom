# W3C Trace Core Evidence

Date: 2026-07-16

OpenSpec tasks: 7.1 and 7.4

## Implemented contracts

- Newly generated trace and span identifiers are nonzero W3C-compatible hexadecimal values. Explicit historical identifiers remain readable but invalid legacy context is never injected into an outbound carrier.
- `TraceContext.root()`, `child()`, `to_dict()`, `from_dict()`, and `trace_fields()` remain available and propagate Agent, Tool, Memory, and Artifact business identifiers through immutable canonical snapshots.
- Redaction uses exact normalized credential fields plus schema-defined paths. It does not use substring matching, so ordinary keys that merely contain words such as `token` are preserved while registered credential forms are redacted.
- The shared propagation core bounds carrier items, traceparent, tracestate, and baggage; applies allowlists; supports restart or reject trust policies; and emits only bounded diagnostic reason classes.
- The OpenTelemetry API conversion boundary is lazy and optional. The no-op adapter preserves runtime behavior when the dependency or exporter is unavailable.

## Verification results

```text
framework event and trace contract tests: 489 passed
Agent, Tool, Memory, and Workflow trace compatibility tests: 43 passed
framework.events import without optional telemetry setup: passed
git diff --check: passed
```

Transport boundary integration, Resource/InstrumentationScope, span links, and sampling/metric safety remain tracked by tasks 7.2, 7.3, and 7.5.
