# research-run-persistence Specification

## Purpose
Define integrity-validated, restart-safe Research run and artifact persistence,
including deterministic latest selection, run-scoped publication, and atomic
filesystem recovery semantics.
## Requirements
### Requirement: Research results are stored as validated versioned JSON
The production Research run store SHALL persist each completed runtime result as atomic versioned JSON with run id, paper id, complete typed result projection, artifact references, and a checksum. Reads SHALL validate schema, identity, checksum, canonical path containment, and regular-file kind before reconstruction.

#### Scenario: Analysis completes
- **WHEN** `ResearchSinglePaperRuntime` returns a result
- **THEN** the service durably commits the validated run record before returning success
- **AND** no pickle, unsafe deserialization, or process-global map is the production source of truth

#### Scenario: Stored result is tampered
- **WHEN** the record bytes, checksum, run id, or paper id no longer match
- **THEN** the store raises typed corruption before exposing analysis, reader, answer, or trace data

### Requirement: Research query behavior survives restart
The durable run store SHALL reconstruct the domain result required by `get_analysis`, `get_reader`, `ask_paper`, and `get_trace` after a new service instance starts with the same storage root.

#### Scenario: Service is reconstructed
- **WHEN** one process saves a successful paper run and another service instance opens the same root
- **THEN** paper analysis, reader payload, trace, quality, and artifact references match the committed result

#### Scenario: Latest paper run is requested
- **WHEN** multiple valid runs exist for one paper
- **THEN** the store deterministically returns the latest committed run according to its persisted index/commit metadata

### Requirement: Harness artifact publication is run-scoped and integrity-protected
The production Harness artifact adapter SHALL bind one validated run id for the duration of a Research execution and SHALL write canonical artifact paths, checksums, metadata, and manifest references through the hardened artifact runtime.

#### Scenario: Research publishes analysis artifacts
- **WHEN** a run emits analysis, reader, quality, RAG, context, trace, or transcript artifacts
- **THEN** each artifact is written under that run only and returns a checksum-bearing reference
- **AND** the run manifest records the artifact path and integrity metadata

#### Scenario: Concurrent runs publish the same artifact type
- **WHEN** two Research requests write `research-analysis` concurrently
- **THEN** each write remains under its own run binding
- **AND** neither adapter reads shared mutable run-id state

#### Scenario: Artifact reference is read
- **WHEN** the adapter resolves a persisted Harness artifact reference
- **THEN** it verifies canonical path and checksum before decoding JSON

### Requirement: Research persistence writes are atomic and recoverable
Run records, latest-by-paper indexes, and Research artifacts SHALL use temp-write, flush, atomic replace, and owned-temp cleanup semantics appropriate to the local filesystem. A failed update SHALL leave the last committed record readable.

#### Scenario: Record replace fails
- **WHEN** an injected filesystem failure occurs before atomic replacement
- **THEN** the prior committed run/index remains readable
- **AND** no partial record is treated as current

#### Scenario: Concurrent writers update one paper index
- **WHEN** multiple runs for the same paper commit concurrently
- **THEN** the index remains valid and references only committed run records
