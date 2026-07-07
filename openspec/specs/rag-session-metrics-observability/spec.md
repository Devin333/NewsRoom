# rag-session-metrics-observability Specification

## Purpose
TBD - created by archiving change rag-session-metrics-observability. Update Purpose after archive.
## Requirements
### Requirement: Bounded RAG sessions expose deterministic metrics
The framework SHALL attach a deterministic metrics payload to every `RAGSessionResult`.

#### Scenario: Answered session metrics are emitted
- **WHEN** a bounded RAG session returns a verified answer
- **THEN** metrics SHALL include final status, final decision type, transcript event count, budget usage, evidence counts, answer attempt count, and gate failure counters

#### Scenario: Abstained session metrics are emitted
- **WHEN** a bounded RAG session abstains after answer verification fails
- **THEN** metrics SHALL include the abstained status, answer attempts, failed gate counts, and answer presence flags

### Requirement: Gated paper RAG responses surface session metrics
The paper RAG service SHALL include bounded session metrics in the gated `rag_ask(generate=True)` response payload.

#### Scenario: Gated response includes operational counters
- **WHEN** the service returns a gated harness answer or abstention
- **THEN** the response `metrics` object SHALL include the session status, decision type, transcript event count, budget usage, evidence counts, and generation counters while preserving existing metric keys
