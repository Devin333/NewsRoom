## Why

PRD 16 requires PDF parsing to avoid a single-parser failure mode: MinerU can produce high-quality structure but may fail, while Marker is a stronger fallback. The current dispatcher selects one backend at a time and cannot record parser attempts or reject low-quality parser output before ingestion.

## What Changes

- Add a deterministic `DocumentQualityProbe` that evaluates parsed `ResearchDocument` completeness.
- Add `CascadeDocumentParser` for PDF bytes: try configured backends in order, reject failed/low-quality attempts, and fall back to PyMuPDF text extraction.
- Add parser attempt metadata to the final document and chunk manifest entries so parser choice and fallback reasons are traceable.
- Wire the default paper chunk pipeline to use the parser cascade while preserving explicit single-backend selection for bake-off tools.
- Add tests for success, parse error fallback, quality rejection fallback, PyMuPDF terminal fallback, and factory wiring.

## Capabilities

### New Capabilities

- `paper-parser-cascade-quality-probe`: Paper PDF parsing can run a traceable parser cascade with deterministic quality gates and a PyMuPDF text fallback.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/document/cascade_parser.py`
  - `business/research/document/pdf_parser_backend.py`
  - `business/research/document/chunk_manifest.py`
  - `interfaces/services/paper_rag_factory.py`
  - parser and factory tests
- No external API contract change to `RetrievalResult` or answer generation.
