# RAG Session Metrics Observability

## Why

The enterprise RAG review still lists basic RAG-path metrics as missing. The bounded RAG session already records durable transcript events, but callers must parse the transcript manually to know outcome, budget usage, gate failures, answer attempts, or supplemental rounds.

## What Changes

- Add deterministic `RAGSessionMetrics` for bounded RAG sessions.
- Populate metrics on every `RAGSessionResult`.
- Surface gated paper RAG session metrics in the service payload.
- Add tests that prove answer and abstention paths expose the counters needed for operational inspection.

## Out Of Scope

- Prometheus/OpenTelemetry exporters.
- Persistent metrics storage.
- Tenant-level dashboards.
