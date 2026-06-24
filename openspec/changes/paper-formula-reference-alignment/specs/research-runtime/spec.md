## ADDED Requirements

### Requirement: Research Formula Reference Metadata
Research runtime SHALL expose formula reference metadata that distinguishes primary formula explanation from explicit later references.

#### Scenario: RAG can expand formula evidence
- **WHEN** Research RAG retrieves a formula chunk
- **THEN** the chunk metadata MUST provide the formula location, primary parent strategy, and explicit body-reference paragraph ids when detected
- **AND** downstream evidence assembly MUST be able to trace the formula back to its original source locator
