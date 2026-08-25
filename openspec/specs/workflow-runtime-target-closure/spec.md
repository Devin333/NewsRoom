# workflow-runtime-target-closure Specification

## Purpose
Historical provenance for the retired Workflow target-state capability. Graph-only orchestration owns the live contract.

## Requirements
### Requirement: Retired Workflow capability remains history-only
The system SHALL retain this capability only as archived provenance and SHALL NOT expose its models, constructors, imports, or runtime authority in active production code.

#### Scenario: Legacy capability is encountered
- **WHEN** an active source, registry, interface, or runtime attempts to use the retired Workflow target-state capability
- **THEN** the architecture gate rejects the dependency with a typed `legacy_orchestration_not_supported` diagnostic
- **AND** no compatibility facade or fallback execution path is created
