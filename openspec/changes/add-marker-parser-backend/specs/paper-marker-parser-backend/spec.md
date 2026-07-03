## ADDED Requirements

### Requirement: Marker is a selectable PDF parser backend
Paper PDF parsing SHALL accept `marker` anywhere a PDF parser backend name is accepted for Nougat and MinerU.

#### Scenario: Dispatcher selects Marker
- **WHEN** a caller requests PDF parser backend `marker`
- **THEN** the PDF parser dispatcher returns a Marker-backed parser
- **AND** `ArxivDocumentParser` can parse PDF bytes through that backend

### Requirement: Marker output is normalized into ResearchDocument
The Marker parser SHALL convert Marker parser artifacts into a `ResearchDocument` with normalized sections, figures, tables, equations, source locators, and parse metadata.

#### Scenario: Marker JSON contains text and special elements
- **WHEN** Marker produces JSON blocks for text, figure, table, and equation content
- **THEN** the parser returns corresponding `ResearchSection`, `ResearchFigure`, `ResearchTable`, and `ResearchEquation` objects
- **AND** each element records `parse_source: marker`
- **AND** available page and bbox data are represented in `source_locator` metadata

### Requirement: Marker is available to parser bake-off ingestion
Parser bake-off and benchmark ingestion CLIs SHALL expose `marker` as a backend choice.

#### Scenario: CLI backend choices include Marker
- **WHEN** parser ingest CLI argument parsers are built
- **THEN** their `--pdf-parser-backend` choices include `marker`
