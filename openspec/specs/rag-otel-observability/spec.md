# rag-otel-observability Specification

## Purpose
TBD - created by archiving change rag-otel-observability. Update Purpose after archive.
## Requirements
### Requirement: Bounded RAG emits OpenTelemetry session spans
Bounded Harness RAG SHALL expose optional OpenTelemetry instrumentation for each session run without requiring an SDK exporter at framework import time.

#### Scenario: Session span records final outcome
- **WHEN** a bounded RAG session completes
- **THEN** the session span records final status, decision type, transcript event count, budget usage, evidence counts, answer counters, supplemental-round counters, and gate failure counters

#### Scenario: OpenTelemetry is not installed
- **WHEN** the OpenTelemetry API package is unavailable
- **THEN** bounded RAG sessions still run successfully without telemetry side effects

### Requirement: Bounded RAG emits step spans
Bounded Harness RAG SHALL emit nested OpenTelemetry spans for each executed retrieval, source-read, or memory-recall step.

#### Scenario: Retrieval step span records operational counts
- **WHEN** a RAG retrieval step executes
- **THEN** the step span records the step id, operation, corpus/scope, result item count, source ref count, artifact ref count, memory ref count, and error count

### Requirement: Bounded RAG mirrors transcript events safely
Bounded Harness RAG SHALL mirror transcript event names into OpenTelemetry span events using redacted and low-cardinality attributes.

#### Scenario: Transcript event becomes OTel event
- **WHEN** a RAG transcript event is recorded
- **THEN** the active session span receives an OTel event with the RAG event name and derived counts/status fields

#### Scenario: Sensitive payload fields are excluded
- **WHEN** telemetry attributes or events are emitted
- **THEN** they do not include raw question text, generated answer text, evidence summaries, user ids, or memory namespaces

### Requirement: Paper RAG service surfaces trace metadata
Paper RAG gated responses SHALL expose trace metadata from the bounded RAG session metrics when telemetry is available.

#### Scenario: Service response includes OTel trace ids
- **WHEN** a gated Paper RAG session returns with telemetry trace metadata
- **THEN** the response metrics include the trace id and root span id without exposing raw span payloads
