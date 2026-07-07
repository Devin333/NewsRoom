## ADDED Requirements

### Requirement: Interface operational docs are present
The repository SHALL include the required interface documentation files for SDK usage, web console operations, and MCP operations.

#### Scenario: Interface docs contract check
- **WHEN** the interface documentation contract test scans required docs
- **THEN** `docs/sdk/python.md`, `docs/web-console.md`, and `docs/mcp.md` SHALL exist
- **AND** the repository README SHALL link to those files

### Requirement: MCP docs describe dangerous tool confirmation metadata
The MCP documentation SHALL describe how dangerous external-write tools expose confirmation metadata.

#### Scenario: Run cancellation metadata is documented
- **WHEN** an operator reads `docs/mcp.md`
- **THEN** the documentation SHALL mention `news.run.cancel`
- **AND** it SHALL describe `requires_confirmation`
- **AND** it SHALL describe `side_effect_level`
- **AND** it SHALL describe `external_write`

### Requirement: Transcript audit persistence is best-effort for gated asks
The Paper RAG service SHALL preserve a completed gated ask response when transcript audit persistence fails.

#### Scenario: Transcript store failure does not fail answer response
- **WHEN** `PaperRagApplicationService.rag_ask()` is called with `generate=True`
- **AND** the bounded RAG session produces a response
- **AND** the transcript store raises while persisting the transcript
- **THEN** the service SHALL return the gated ask payload
- **AND** `transcript_artifact` SHALL include an error payload describing the persistence failure
