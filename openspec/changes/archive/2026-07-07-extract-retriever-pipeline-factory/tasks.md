## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for retriever pipeline factory extraction.

## 2. Pipeline Factory

- [x] 2.1 Add `retrieval/factory.py` with `build_retrieval_pipeline(...)`.
- [x] 2.2 Move channel, stage, reranker cascade, expander, and pipeline construction from `ResearchRetriever.__init__` into the factory.
- [x] 2.3 Update `ResearchRetriever` to call the factory while keeping constructor parameters and behavior unchanged.
- [x] 2.4 Export the factory from the retrieval package.

## 3. Tests And Validation

- [x] 3.1 Add focused tests for factory compatibility and optional-adapter metadata preservation.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-retriever-pipeline-factory --strict`.
