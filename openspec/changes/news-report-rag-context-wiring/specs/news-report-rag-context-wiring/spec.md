## ADDED Requirements

### Requirement: News report output carries retrieved context when configured
The news report output pipeline SHALL project retrieved report memory context into the report payload when a report context provider is configured.

#### Scenario: Retrieved context is added to report metadata and sections
- **WHEN** `BoardOutputPipeline` builds an AI news board output with a configured report context provider
- **AND** the provider returns non-empty prompt context
- **THEN** the report metadata includes `rag_context`
- **AND** the report sections include a `Retrieved Context` evidence section containing the prompt context
- **AND** the board output metadata exposes the same `rag_context`

### Requirement: News report output remains robust without retrieved context
The news report output pipeline SHALL preserve existing report behavior when retrieved context is unavailable.

#### Scenario: No provider preserves legacy output shape
- **WHEN** `BoardOutputPipeline` builds board output without a report context provider
- **THEN** the report is built without `rag_context`
- **AND** no `Retrieved Context` section is added

#### Scenario: Provider failure records diagnostics
- **WHEN** a configured report context provider fails during recall
- **THEN** report construction still succeeds
- **AND** report metadata includes a `rag_context` payload with `memory_available=false`
- **AND** the diagnostic reason includes the provider failure class
