# approval-workflow-resume-interfaces Specification

## Purpose
Historical provenance for the retired Workflow approval-resume capability. Graph approval resume interfaces own the live contract.

## Requirements
### Requirement: Retired Workflow approval surface remains history-only
The system SHALL retain this capability only as archived provenance and SHALL NOT expose Workflow resume endpoints, commands, MCP tools, SDK methods, state patches, or compatibility aliases in active interfaces.

#### Scenario: Retired approval surface is called
- **WHEN** a client requests a retired Workflow approval-resume surface
- **THEN** the interface returns a typed `legacy_orchestration_not_supported` diagnostic
- **AND** it does not construct a Workflow runner or mutate Graph state
