## 1. Telemetry Contract

- [x] 1.1 Add optional `opentelemetry-api` dependency metadata.
- [x] 1.2 Add a Harness RAG telemetry helper with no-op fallback, safe attributes, and injectable tracer support.

## 2. Session Integration

- [x] 2.1 Instrument `BoundedRAGSessionController.run()` with a session span, safe transcript events, final outcome attributes, and exception recording.
- [x] 2.2 Instrument retrieval/source/memory step execution with nested step spans and operational count attributes.
- [x] 2.3 Add trace metadata fields to `RAGSessionMetrics` and gated Paper RAG metrics.

## 3. Verification

- [x] 3.1 Add framework tests for session spans, step spans, safe event attributes, final metrics, and no-op behavior.
- [x] 3.2 Validate the OpenSpec change and run targeted tests, compile, smoke, all OpenSpec strict validation, and diff checks.
