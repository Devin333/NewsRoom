## 1. OpenSpec And Dispatcher

- [x] 1.1 Add Marker parser backend proposal, design, spec, and task artifacts.
- [x] 1.2 Extend `PdfParserBackendName`, backend validation, and parser factory to include `marker`.
- [x] 1.3 Export `MarkerPdfDocumentParser` from the document package.

## 2. Marker Parser Implementation

- [x] 2.1 Implement Docker command construction and timeout handling for Marker.
- [x] 2.2 Convert Marker JSON and Markdown artifacts into `ResearchDocument` sections, figures, tables, and equations.
- [x] 2.3 Preserve image/table assets, source locators, parser output references, warnings, and parse quality metadata.

## 3. CLI Wiring And Tests

- [x] 3.1 Add `marker` to PDF parser backend choices in benchmark and parser bake-off CLIs.
- [x] 3.2 Add tests for Marker output conversion and dispatcher selection.
- [x] 3.3 Add tests for CLI backend choices.
- [x] 3.4 Run targeted tests, compile checks, and `openspec validate add-marker-parser-backend --strict`.
