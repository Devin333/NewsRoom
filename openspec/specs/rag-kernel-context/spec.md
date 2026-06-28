# rag-kernel-context Specification

## Purpose
TBD - created by archiving change rag-kernel-context-retrieval. Update Purpose after archive.
## Requirements
### Requirement: Context budget trims evidence without mutating provenance
The system SHALL provide context budget helpers that trim evidence by max item count and max text characters while preserving selected evidence objects and their source locators.

#### Scenario: Context is trimmed by item and text budget
- **WHEN** candidate evidence exceeds the configured context budget
- **THEN** the helper returns only evidence that fits the budget
- **AND** selected evidence keeps its original source locator and metadata

### Requirement: Citation resolution supports main and overlap spans
The system SHALL resolve citation provenance from evidence metadata containing `main_span`, `overlap_spans`, and `content_span_unit`.

#### Scenario: Citation lands inside overlap span
- **WHEN** a citation character range falls inside an overlap span
- **THEN** the resolver returns the overlap span's origin chunk id and origin source locator
- **AND** citations outside overlap spans resolve to the current evidence chunk and source locator

### Requirement: Context assembler orders, deduplicates, and budgets evidence
The system SHALL provide a basic context assembler that orders evidence by score, deduplicates repeated chunks, and applies a context budget.

#### Scenario: Assembler returns compact context evidence
- **WHEN** unordered evidence contains duplicates and exceeds budget
- **THEN** the assembler returns score-ordered deduplicated evidence within budget
- **AND** it does not alter evidence text, metadata, or source locator values

