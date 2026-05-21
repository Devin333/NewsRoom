## ADDED Requirements

### Requirement: Output pipeline orchestration boundary
The output pipeline SHALL delegate BoardCard, DetailPage, Insight, Report, section composition, and output quality logic to focused output-layer helpers while preserving the existing `BoardOutputPipeline.build_board_output(...)` public entrypoint.

#### Scenario: Split builders preserve board output
- **WHEN** `BoardOutputPipeline` builds board output from signals, extraction results, relations, analysis, and context
- **THEN** it returns BoardOutput with cards, detail pages, insights, sections, stats, and report metadata generated through the split helpers

#### Scenario: Board card output remains interface safe
- **WHEN** a BoardCard is serialized from the output pipeline
- **THEN** it MUST NOT expose `raw_payload` and MUST include evidence refs, provenance, quality, and ranking reason
