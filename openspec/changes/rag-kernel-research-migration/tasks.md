## 1. Paper Evidence Metadata Projection

- [x] 1.1 Add a Research adapter helper for `PaperChunk` to `EvidencePack.metadata` projection
- [x] 1.2 Preserve existing Paper metadata fields used by formula, table, figure, parent, field-score, and overlap retrieval paths
- [x] 1.3 Expose RAG kernel metadata keys for document id, chunk id, score, score breakdown, and source locator

## 2. Retrieval Port Wiring

- [x] 2.1 Rewire `PaperChunkRetrievalPort` to use the Research adapter helper
- [x] 2.2 Keep `EvidencePack` summary, source refs, confidence, freshness, lineage, dedup order, and collection metadata unchanged

## 3. Tests and Boundary Checks

- [x] 3.1 Add adapter tests for kernel metadata projection
- [x] 3.2 Extend retrieval port tests to verify existing visual/formula metadata plus new kernel metadata
- [x] 3.3 Run import-boundary scan proving `framework/rag` remains free of Research imports and paper parser concepts

## 4. Verification

- [x] 4.1 Run `openspec validate rag-kernel-research-migration --strict`
- [x] 4.2 Run targeted framework/harness/Research RAG tests
- [x] 4.3 Run `python -m scripts.dev compile`
