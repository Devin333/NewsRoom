# Design

## Context

Bounded Harness RAG already records durable transcript events and deterministic `RAGSessionMetrics`. That is enough for post-run inspection, but live operations still cannot see RAG sessions as trace spans in an OpenTelemetry pipeline. Existing framework workflow code has internal trace ids, yet the RAG controller does not expose OTel API spans.

## Goals / Non-Goals

**Goals:**
- Instrument `BoundedRAGSessionController.run()` with an optional OTel session span.
- Instrument retrieval/source/memory step execution with nested OTel step spans.
- Add redacted/count-only OTel events corresponding to RAG transcript events.
- Attach final status, decision, budget, evidence, gate, answer, and supplemental-round counters as span attributes.
- Keep OpenTelemetry SDK/exporter configuration outside framework code.

**Non-Goals:**
- Add Prometheus metrics.
- Add persistent telemetry storage.
- Export full prompts, questions, answers, evidence summaries, user ids, or memory namespaces as span attributes.
- Replace durable transcripts or `RAGSessionMetrics`.

## Decisions

1. Use `opentelemetry-api` as an optional dependency.
   - Rationale: libraries should depend only on the API; applications and deployments choose SDK/exporters.
   - Alternative: add `opentelemetry-sdk` and configure exporters in framework code. Rejected because exporter configuration is deployment-specific.

2. Add a small `framework.harness.rag.telemetry` helper.
   - Rationale: the controller should not be littered with optional imports, attribute redaction rules, or OTel object shape checks.
   - Alternative: call `trace.get_tracer()` directly throughout `session.py`. Rejected because it makes tests and redaction harder to reason about.

3. Record transcript event names as OTel events with safe derived attributes only.
   - Rationale: transcript payloads may contain source text, questions, generated answers, or large nested objects. OTel events should support diagnosis without leaking payload content.
   - Alternative: attach full event payloads. Rejected for privacy, cost, and cardinality reasons.

4. Keep telemetry injectable.
   - Rationale: focused tests can use a recording tracer without requiring OpenTelemetry SDK installation.
   - Alternative: rely on global tracer provider side effects in tests. Rejected because it would make tests environment-dependent.

## Risks / Trade-offs

- [Risk] Operators may expect exporters to work automatically after this change. -> Mitigation: the optional dependency is explicit and docs/spec state that SDK/provider/exporters remain deployment concerns.
- [Risk] Span attributes can become high-cardinality or sensitive. -> Mitigation: use fixed attribute keys, query hashes, counts, and tenant id only; exclude user id, memory namespace, question, answer, and evidence text.
- [Risk] Additional span creation could add overhead. -> Mitigation: the default API-only path is no-op unless a tracer provider/exporter is configured.
