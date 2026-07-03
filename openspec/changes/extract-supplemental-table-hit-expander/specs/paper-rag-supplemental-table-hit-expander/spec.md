## ADDED Requirements

### Requirement: Supplemental table hits are delegated to an expander module
Paper RAG retrieval SHALL inject supplemental table hits through a dedicated supplemental table hit expander.

#### Scenario: Result query injects table when no table child exists
- **WHEN** a result-style query has no table child after primary retrieval
- **THEN** the expander searches table chunks, scores accepted table hits, and tags them with `supplemental_reason`

#### Scenario: Existing table child suppresses supplemental table search
- **WHEN** primary retrieval already returned a table child
- **THEN** the expander returns no supplemental table chunks

#### Scenario: Search failure degrades gracefully
- **WHEN** supplemental table search fails
- **THEN** the expander logs the failure and returns no supplemental table chunks without raising
