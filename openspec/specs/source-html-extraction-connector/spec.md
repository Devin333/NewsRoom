# source-html-extraction-connector Specification

## Purpose
TBD - created by archiving change source-html-extraction-connector. Update Purpose after archive.
## Requirements
### Requirement: Source pipeline extracts HTML pages into raw source items
The system SHALL provide an HTML connector that extracts article metadata and
visible text from a configured HTML source page.

#### Scenario: HTML page has article metadata
- **WHEN** an HTML page includes title, canonical URL, description, published
  time, author metadata, and article text
- **THEN** the connector returns one `RawSourceItem` containing the extracted
  metadata, text, canonical URL, and extraction confidence

#### Scenario: HTML page has only minimal content
- **WHEN** an HTML page lacks rich metadata but has body text
- **THEN** the connector falls back to source name, source URL, and extracted
  visible text

#### Scenario: HTML page cannot produce an item
- **WHEN** the fetched HTML response is empty
- **THEN** the connector returns a structured source error
