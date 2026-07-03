## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for retrieval pipeline entrypoint extraction.

## 2. Pipeline Entrypoint

- [x] 2.1 Add `retrieval/pipeline.py` with `RetrievalPipeline`.
- [x] 2.2 Move `retrieve()` orchestration and metrics helper functions from `ResearchRetriever` into the pipeline without changing behavior.
- [x] 2.3 Update `ResearchRetriever` to construct and delegate to the pipeline.
- [x] 2.4 Export `RetrievalPipeline` from the retrieval package.

## 3. Tests And Validation

- [x] 3.1 Add focused pipeline delegation/parity tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-retrieval-pipeline-entrypoint --strict`.
