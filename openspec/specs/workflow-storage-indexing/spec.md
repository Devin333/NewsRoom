# workflow-storage-indexing Specification

## Purpose
Historical provenance for the retired Workflow storage-indexing capability. Graph storage indexing owns the live artifact and event contracts.

## Requirements
### Requirement: Retired Workflow storage capability remains history-only
The system SHALL retain this capability only as archived provenance and SHALL NOT index live Graph artifacts or events through Workflow identifiers, writers, or projections.

#### Scenario: Legacy storage record is encountered
- **WHEN** a live storage path receives a retired Workflow artifact or event record
- **THEN** it rejects the record or routes it to an explicit history-only quarantine
- **AND** it does not write a live index entry or event projection
