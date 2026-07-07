# RAG OTel Observability

## Why

The enterprise RAG review still lists online observability as incomplete after deterministic metrics landed. Operators can inspect `RAGSessionMetrics` and transcripts after a run, but the live bounded RAG path does not emit OpenTelemetry spans or events for session, retrieval, verification, generation, and gate failures.

## What Changes

- Add an optional OpenTelemetry API bridge for Harness RAG sessions.
- Emit a session span for each bounded RAG run with safe operational attributes and final status/decision metrics.
- Emit nested step spans for retrieval/source/memory steps with counts and error status.
- Mirror RAG transcript event names into OTel span events using redacted/count-only attributes.
- Add an `observability` optional dependency group for `opentelemetry-api`; do not configure SDK exporters in framework code.

## Capabilities

### New Capabilities
- `rag-otel-observability`: optional OpenTelemetry instrumentation for bounded Harness RAG sessions.

### Modified Capabilities

## Impact

Affected code includes `framework/harness/rag` session orchestration, a new telemetry helper module, exports, optional dependency metadata, and focused framework tests. There is no persistence migration and no mandatory runtime dependency for deployments that do not install OpenTelemetry.
