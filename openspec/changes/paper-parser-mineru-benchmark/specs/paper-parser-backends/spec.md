# paper-parser-backends

## ADDED Requirements

### Requirement: MinerU parser backend

The system SHALL provide a Docker-backed MinerU PDF parser backend that can be
selected explicitly for benchmark ingest without changing the default parser.

#### Scenario: Select MinerU for PDF parsing

- **WHEN** `NEWSROOM_PDF_PARSER_BACKEND=mineru` or
  `--pdf-parser-backend mineru` is configured
- **THEN** PDF source packages are parsed by the MinerU backend
- **AND** the resulting `ResearchDocument.metadata.parse_source` is `mineru`

### Requirement: Repository-local parser runtime artifacts

The MinerU backend SHALL write parser runtime inputs and outputs under the
repository `.newsroom` tree by default.

#### Scenario: Default runtime root

- **WHEN** no parser runtime root override is configured
- **THEN** the backend stages input and output under
  `.newsroom/parser-runs/mineru/<paper_id>`
