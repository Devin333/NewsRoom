## MODIFIED Requirements

### Requirement: Interface board DTOs
Interfaces SHALL consume board services and output DTOs rather than bypassing business services or reading storage directly, and they MUST NOT expose raw payload fields.

#### Scenario: Interfaces consume board output
- **WHEN** CLI, API, MCP, or web contract helpers render board or cross-board output
- **THEN** they use BoardRunResult or output DTO data from business services and preserve ranking, evidence, quality, guard, and policy metadata without exposing raw payloads
