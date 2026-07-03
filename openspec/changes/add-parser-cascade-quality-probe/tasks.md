## 1. Cascade Parser Core

- [x] 1.1 Add OpenSpec proposal, design, spec, and task artifacts.
- [x] 1.2 Implement `DocumentQualityProbe` with deterministic thresholds and metrics.
- [x] 1.3 Implement `PyMuPDFTextDocumentParser` terminal fallback.
- [x] 1.4 Implement `CascadeDocumentParser` attempt tracking and quality rejection.
- [x] 1.5 Implement `CascadeArxivDocumentParser` so LaTeX stays unchanged and PDF uses cascade.

## 2. Wiring And Manifest

- [x] 2.1 Add parser cascade factory helpers and environment parsing.
- [x] 2.2 Wire `interfaces.services.paper_rag_factory.build_chunk_pipeline` to the cascade parser by default.
- [x] 2.3 Add parser cascade summary to `ChunkManifestManager.write`.

## 3. Tests And Validation

- [x] 3.1 Add unit tests for first-pass success, parse-error fallback, quality rejection fallback, and PyMuPDF fallback.
- [x] 3.2 Add tests for chunk manifest parser cascade metadata.
- [x] 3.3 Add tests for default factory cascade wiring.
- [x] 3.4 Run targeted tests, compile checks, and `openspec validate add-parser-cascade-quality-probe --strict`.
