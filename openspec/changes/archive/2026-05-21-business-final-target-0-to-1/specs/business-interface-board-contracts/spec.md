## ADDED Requirements

### Requirement: Interfaces consume board DTOs
CLI, API, MCP, and Web-facing contracts SHALL consume board services and output DTOs instead of internal raw Signal, Relation, Claim, or concrete storage objects.

#### Scenario: Interface board output
- **WHEN** an interface requests board data
- **THEN** it receives BoardOutput or BoardRunResult DTOs from the board application service

### Requirement: Interface dependency boundary
Interface-level board contracts MUST NOT bypass business services to access concrete storage for board presentation data.

#### Scenario: Boundary test rejects storage bypass
- **WHEN** dependency tests scan interface board contract modules
- **THEN** they find no direct board presentation dependency on concrete postgres, qdrant, or redis storage modules
