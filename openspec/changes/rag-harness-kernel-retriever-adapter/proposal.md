## Why

The decoupling PRD's V5 target says Harness RAG should cooperate with `framework/rag` through generic retrieval/context contracts, while Research should provide the Paper-specific corpus adapter. The existing Paper retrieval port directly converted Paper chunks into Harness `EvidencePack` values, which kept the old path working but did not make `RAGRetrieverPort` and `RAGEvidence` the integration boundary.

## What Changes

- Add a Harness-owned `KernelRAGRetrieverHarnessAdapter` that adapts any `RAGRetrieverPort` into the existing Harness `RetrievalPort`.
- Add a Research-owned `PaperKernelRAGRetriever` that maps generic `RAGQuery` values into `ResearchRetriever` calls and returns `RAGEvidence`.
- Rewire `PaperChunkRetrievalPort` to compose the Paper kernel retriever with the Harness kernel adapter while preserving existing `EvidencePackCollection` output.
- Keep Paper query routing, ranking, metadata shape, and benchmark-facing behavior unchanged.

## Capabilities

### New Capabilities

- `rag-harness-kernel-retriever-adapter`: Harness can consume generic `framework.rag.core.RAGRetrieverPort` implementations without importing Research.
- `paper-kernel-rag-retriever`: Research exposes Paper RAG retrieval through the generic `RAGRetrieverPort` evidence contract.

### Modified Capabilities

- `paper-chunk-retrieval-port-kernel-wiring`: the existing Paper Harness retrieval port now delegates through the kernel retriever adapter path.

## Impact

Affected code is limited to Harness RAG adapter wiring, Research retrieval port wiring, Paper adapter metadata projection, focused tests, and this OpenSpec change. No retrieval ranking behavior is intentionally changed.
