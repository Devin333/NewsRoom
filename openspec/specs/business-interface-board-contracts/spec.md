# business-interface-board-contracts Specification

## Purpose
TBD - created by archiving change business-final-target-0-to-1. Update Purpose after archive.
## Requirements
### Requirement: Interfaces consume board DTOs
CLI, API, MCP, Web-facing contracts, and workflow facade services SHALL consume board services and output DTOs instead of internal raw Signal, Relation, Claim, or concrete storage objects.

#### Scenario: Interface board output
- **WHEN** an interface requests board data
- **THEN** it receives BoardOutput or BoardRunResult DTOs from the board application service

#### Scenario: Workflow facade output
- **WHEN** an interface service runs a board workflow or final business run
- **THEN** it receives DTOs containing workflow results, cross-board graph intelligence, quality summaries, feedback events, learning signals, policy candidates, guard results, and artifact/evidence/memory refs without exposing raw payloads

### Requirement: Interface dependency boundary
Interface-level board contracts MUST NOT bypass business services to access concrete storage for board presentation data.

#### Scenario: Boundary test rejects storage bypass
- **WHEN** dependency tests scan interface board contract modules
- **THEN** they find no direct board presentation dependency on concrete postgres, qdrant, or redis storage modules

