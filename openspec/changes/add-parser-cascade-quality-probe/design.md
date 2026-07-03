## Context

PDF ingestion currently routes through `ArxivDocumentParser`, which delegates PDF bytes to a single backend selected by `NEWSROOM_PDF_PARSER_BACKEND` or an explicit constructor argument. PRD 16 requires a default cascade of MinerU, Marker, and PyMuPDF fallback, with deterministic quality checks and traceable attempts.

## Goals / Non-Goals

**Goals:**

- Introduce a parser cascade that implements the existing `DocumentParserPort`.
- Keep LaTeX parsing unchanged; cascade applies only to PDF bytes.
- Record all attempts in final document metadata.
- Reject low-quality parser outputs deterministically before falling through to the next backend.
- Provide a guaranteed PyMuPDF text-only fallback so every readable PDF can produce sections.

**Non-Goals:**

- Do not tune final parser ranking with LLMs.
- Do not implement parser bake-off penalized metrics in this change.
- Do not change retrieval result or RAG answer contracts.

## Decisions

- **Cascade wrapper around source detection:** Implement `CascadeArxivDocumentParser` as the chunk-pipeline default parser. It detects source format; LaTeX delegates to `LatexSourceParser`; PDF delegates to `CascadeDocumentParser`.
- **Backends remain normal parsers:** MinerU and Marker keep their independent parser classes. Cascade receives `(backend_name, parser)` pairs and calls `parse` through the common interface.
- **Quality probe from document fields:** `DocumentQualityProbe` checks section count, body character count, non-empty section ratio, replacement character ratio, and optional table row coverage when tables exist.
- **PyMuPDF fallback is terminal:** If all configured backends fail or are rejected, `PyMuPDFTextDocumentParser` extracts page text into page sections and marks `degraded=true`.
- **Trace metadata shape:** Final `ResearchDocument.metadata["parser_cascade"]` stores `used_backend`, `degraded`, and `attempts`. Each attempt stores backend, status, reason, elapsed milliseconds, and quality metrics when available.

## Risks / Trade-offs

- **Strict probe rejects valid short papers** -> Thresholds are configurable through environment variables and default to moderate values.
- **Cascade increases ingest latency** -> Attempts stop on first passing backend; failures and timeouts are recorded for observability.
- **PyMuPDF fallback loses structure** -> It is marked degraded and used only after all structured parsers fail/reject.
