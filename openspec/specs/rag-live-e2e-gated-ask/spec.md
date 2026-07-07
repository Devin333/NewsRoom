# rag-live-e2e-gated-ask Specification

## Purpose
TBD - created by archiving change live-e2e-gated-ask. Update Purpose after archive.
## Requirements
### Requirement: Live E2E covers gated ask closure
The live RAG E2E suite SHALL exercise the gated ask path after live paper chunk ingestion.

#### Scenario: Gated ask runs over live retrieved chunks
- **WHEN** `scripts.dev test-rag-live-e2e` runs with live Qdrant/Postgres services configured
- **THEN** the suite runs a `rag_ask(generate=True)` request against the ingested paper
- **AND** the request uses live retrieved chunks as the context source

### Requirement: Live gated ask test avoids external LLM dependency
The live gated ask E2E test SHALL use a deterministic local answer worker.

#### Scenario: Gated answer worker is local
- **WHEN** the live gated ask E2E test builds the session
- **THEN** it injects a grounded local answer worker
- **AND** it does not require external model credentials

### Requirement: Live gated ask payload includes reviewable transcript and gate data
The live gated ask E2E test SHALL assert payload fields needed for review and replay diagnostics.

#### Scenario: Payload contains gated diagnostics
- **WHEN** the gated ask returns
- **THEN** the payload includes terminal status, transcript id, context pack, passages, answer candidate, gate results, and citations
