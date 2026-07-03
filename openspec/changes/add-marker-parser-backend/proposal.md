## Why

PRD 16 requires Marker to enter the main PDF parser backend path so parser bake-off and the upcoming cascade can compare and use it through the same dispatcher as Nougat and MinerU. `ParseSource` already allows `marker`, but the production selector and ingest CLIs cannot run a Marker-backed PDF parse today.

## What Changes

- Add a Docker-backed `MarkerPdfDocumentParser` that parses Marker JSON/Markdown artifacts into `ResearchDocument`.
- Extend the PDF parser dispatcher to accept `marker` through `NEWSROOM_PDF_PARSER_BACKEND`, `ArxivDocumentParser`, and `PdfBackendDocumentParser`.
- Extend parser bake-off and benchmark ingest CLI backend choices from `nougat | mineru` to `nougat | mineru | marker`.
- Add tests for Marker command wiring, Marker output conversion, dispatcher selection, and CLI choice exposure.

## Capabilities

### New Capabilities

- `paper-marker-parser-backend`: Paper PDF parsing can select Marker as a first-class backend and receive normalized document sections, figures, tables, equations, locators, and parser metadata.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/document/marker_pdf_parser.py`
  - `business/research/document/pdf_parser_backend.py`
  - `business/research/document/__init__.py`
  - `business/research/rag/evaluation/paper_benchmark_ingest.py`
  - `business/research/rag/evaluation/paper_parser_bakeoff_ingest.py`
  - `business/research/rag/evaluation/paper_parser_url_bakeoff_ingest.py`
  - PDF parser tests
- Adds no mandatory runtime dependency to the host Python environment; Marker runs through Docker.
