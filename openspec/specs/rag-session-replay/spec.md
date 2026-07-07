# rag-session-replay Specification

## Purpose
TBD - created by archiving change rag-session-replay. Update Purpose after archive.
## Requirements
### Requirement: RAG transcripts can be replayed without live workers
The framework SHALL provide a RAG session replay reader that consumes a recorded `RAGTranscript` and does not call retrieval, memory, tool, or LLM workers.

#### Scenario: Context-pack session is replayed
- **WHEN** a transcript contains plan, step, source verification, context pack, and return events
- **THEN** replay SHALL return the event sequence, gate timeline, final context pack payload, terminal decision, and final status

#### Scenario: Answer session is replayed
- **WHEN** a transcript contains answer candidate, answer verification, and answer return events
- **THEN** replay SHALL include the answer candidate and answer gate results

### Requirement: RAG replay validates transcript shape
The replay reader SHALL reject transcripts that cannot support deterministic inspection.

#### Scenario: Transcript has no events
- **WHEN** replay is requested for an empty transcript
- **THEN** replay SHALL fail with a validation error

#### Scenario: Event is malformed
- **WHEN** an event omits `event_type` or has a non-object payload
- **THEN** replay SHALL fail with a validation error

### Requirement: RAG replay can validate fixed snapshots
The replay reader SHALL validate caller-supplied fixed snapshots for refs recorded by the context pack.

#### Scenario: Snapshot checksums match
- **WHEN** replay is given snapshots for context and artifact refs
- **THEN** replay SHALL mark snapshot checks as passed

#### Scenario: Snapshot checksum mismatches
- **WHEN** a supplied snapshot checksum does not match its payload
- **THEN** replay SHALL mark the replay as not replayable and include the mismatch error
