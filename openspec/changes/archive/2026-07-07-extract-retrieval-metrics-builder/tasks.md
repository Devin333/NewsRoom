## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for retrieval metrics builder extraction.

## 2. Metrics Builder

- [x] 2.1 Add `retrieval/metrics.py` with `RetrievalMetricsBuilder`.
- [x] 2.2 Move metrics dictionary assembly and helper functions from `pipeline.py` into the builder.
- [x] 2.3 Update `RetrievalPipeline` to delegate metrics assembly to the builder.
- [x] 2.4 Export `RetrievalMetricsBuilder` from the retrieval package.

## 3. Tests And Validation

- [x] 3.1 Add focused metrics builder tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-retrieval-metrics-builder --strict`.
