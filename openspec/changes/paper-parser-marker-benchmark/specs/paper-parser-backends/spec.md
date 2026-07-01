# paper-parser-backends

## ADDED Requirements

### Requirement: Marker parser backend

The system SHALL provide a Docker-backed Marker PDF parser backend that can be
selected explicitly for benchmark ingest without changing the default parser.

#### Scenario: Select Marker for PDF parsing

- **WHEN** `NEWSROOM_PDF_PARSER_BACKEND=marker` or
  `--pdf-parser-backend marker` is configured
- **THEN** PDF source packages are parsed by the Marker backend
- **AND** the resulting `ResearchDocument.metadata.parse_source` is `marker`

### Requirement: Repository-local parser runtime artifacts

The Marker backend SHALL write parser runtime inputs and outputs under the
repository `.newsroom` tree by default.

#### Scenario: Default runtime root

- **WHEN** no parser runtime root override is configured
- **THEN** the backend stages input and output under
  `.newsroom/parser-runs/marker/<paper_id>`
