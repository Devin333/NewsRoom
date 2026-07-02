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

### Requirement: PDF-only parser bake-off ingest

The system SHALL provide a parser bake-off ingest path that fetches arXiv PDFs
directly and parses each PDF with the explicitly selected PDF parser backend.

#### Scenario: Run same-PDF parser comparison

- **WHEN** parser bake-off ingest is run with `--pdf-parser-backend mineru`
- **THEN** it fetches the arXiv PDF package instead of the source package
- **AND** it writes per-paper `research_document.json` artifacts under the
  configured papers directory
- **AND** it writes a manifest containing success, skip, and failure counts
