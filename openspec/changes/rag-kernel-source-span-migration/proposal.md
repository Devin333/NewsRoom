## Why

The PRD calls for `framework/rag/context/source_span.py`. Research already stores `main_span` and `overlap_spans` so citation logic can quote the original paragraph when an answer hits overlap text. That span math is domain-neutral and should live in the RAG kernel, while Paper-specific `PaperChunk` wrapping remains in Research.

## What Changes

- Add `framework/rag/context/source_span.py`.
- Introduce `build_main_overlap_span_metadata()`, `resolve_source_span()`, `locate_snippet_span()`, and `remap_span_origin_ids()`.
- Rewire `business/research/document/citation_spans.py` to delegate generic span logic to the kernel while preserving its existing function names and output shape.
- Keep PaperChunk access and document chunking decisions in Research.
- Add framework unit tests for main/overlap span metadata, snippet lookup, source span resolution, and origin id remapping.

## Capabilities

### New Capabilities

- `rag-kernel-source-span`: domain-neutral span metadata and overlap-origin citation resolution.

### Modified Capabilities

- `paper-rag-source-span-migration`: Paper citation span helpers delegate generic span handling to the RAG kernel while preserving Paper-facing APIs.

## Impact

Affected code is limited to `framework/rag/context`, Research citation span wrappers, tests, and this OpenSpec change. Existing Paper chunker and citation behavior remain compatible.
