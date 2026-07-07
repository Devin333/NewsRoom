## ADDED Requirements

### Requirement: Golden-set paper ingest repairs missing corpus artifacts
The system SHALL provide a command that ingests parsed paper artifacts for paper ids referenced by the evidence golden set.

#### Scenario: Golden set references missing papers
- **WHEN** the operator runs `python -m scripts.dev ingest-golden-set-papers`
- **AND** some golden-set paper ids do not have `research_document.json` under the papers directory
- **THEN** the command SHALL attempt to fetch and parse only those missing paper ids by default
- **AND** it SHALL write a manifest containing selected ids and ingest results

#### Scenario: Golden set is already covered
- **WHEN** every golden-set paper id has a parsed research document
- **THEN** the command SHALL report zero selected ids
- **AND** it SHALL return success without fetching papers

### Requirement: Golden-set paper ingest can force regeneration
The command SHALL support forced regeneration when an operator needs to refresh existing parsed artifacts.

#### Scenario: Operator passes force
- **WHEN** the operator runs the command with `--force`
- **THEN** the command SHALL select all paper ids from the golden set
- **AND** it SHALL pass force through to the underlying ingest path
