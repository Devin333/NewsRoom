## 1. Harness Kernel Adapter

- [x] 1.1 Add `KernelRAGRetrieverHarnessAdapter`
- [x] 1.2 Map Harness `RetrievalRequest` to generic `RAGQuery`
- [x] 1.3 Convert returned `RAGEvidence` into Harness `EvidencePackCollection`
- [x] 1.4 Export the adapter from `framework.harness.rag`

## 2. Research Paper Retriever

- [x] 2.1 Add `PaperKernelRAGRetriever`
- [x] 2.2 Map `RAGQuery` to `ResearchRetrievalRequest`
- [x] 2.3 Project Paper chunks into `RAGEvidence` with Paper metadata preserved
- [x] 2.4 Rewire `PaperChunkRetrievalPort` through the kernel adapter while preserving existing collection metadata

## 3. Verification

- [x] 3.1 Run `openspec validate rag-harness-kernel-retriever-adapter --strict`
- [x] 3.2 Run focused Harness adapter and Research retrieval port tests
- [x] 3.3 Run full RAG pytest coverage, compile, and boundary scans
- [x] 3.4 Add Paper RAG Harness integration coverage for `ResearchRAGPolicyBuilder -> BoundedRAGSessionController -> PaperChunkRetrievalPort -> KernelRAGRetrieverHarnessAdapter -> RAGContextPack`
- [x] 3.5 Remove the unused Research RAG policy port that leaked Harness `RAGSessionSpec` through the Research ports package
