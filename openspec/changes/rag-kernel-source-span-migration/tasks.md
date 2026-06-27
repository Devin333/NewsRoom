## 1. Kernel Source Spans

- [x] 1.1 Add `framework/rag/context/source_span.py`
- [x] 1.2 Add main/overlap span metadata builder
- [x] 1.3 Add snippet span locator
- [x] 1.4 Add source span resolver for main vs overlap citations
- [x] 1.5 Add origin chunk id remapping helper
- [x] 1.6 Export source span helpers from `framework/rag/context`

## 2. Research Wiring

- [x] 2.1 Rewire `build_paragraph_span_metadata()` to use kernel metadata builder
- [x] 2.2 Rewire `resolve_citation_span()` to use kernel source span resolver
- [x] 2.3 Rewire `remap_span_origin_ids()` to use kernel remapper
- [x] 2.4 Keep PaperChunk wrapping in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-source-span-migration --strict`
- [x] 3.2 Run framework source span tests and Research citation/chunker/RAG tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
