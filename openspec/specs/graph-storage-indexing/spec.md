# graph-storage-indexing Specification

## Purpose
Define Graph-owned artifact and event indexing contracts for validated run, Graph, node, manifest, and checksum identities.

## Requirements
### Requirement: Graph runs populate the artifact index

The system SHALL index artifacts produced by Graph runs only after their run identifier, Graph identity, terminal manifest and artifact paths validate within the canonical artifact root.

#### Scenario: Graph run completes

- **WHEN** a valid Graph run writes artifacts listed in its verified terminal manifest
- **THEN** the artifact index contains checksum-bound `ArtifactRef` records for those manifest artifacts and their Graph node instances

#### Scenario: Manifest index path escapes the run root

- **WHEN** a Graph manifest artifact path resolves outside the canonical run root
- **THEN** indexing fails without reading external bytes or persisting an index reference

### Requirement: Graph runs populate the event store

The system SHALL persist Graph events into the storage-owned event store only for validated run, Graph and node identities and strictly monotonic stream sequence.

#### Scenario: Graph events are written

- **WHEN** a Graph run with valid identities writes its durable event stream
- **THEN** the event store contains the same checksum-verified Graph event records
- **AND** node events can be queried by node-instance id

#### Scenario: Event identity is unsafe

- **WHEN** event persistence receives an unsafe run, Graph or node identifier
- **THEN** it fails before resolving or writing an event-store path
