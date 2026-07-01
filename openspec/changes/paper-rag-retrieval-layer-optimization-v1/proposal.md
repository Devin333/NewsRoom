## Why

Paper RAG retrieval currently finds correct evidence in most real benchmark cases, but enterprise-grade answering needs stronger top-rank precision and fuller multi-evidence coverage. The next step is to make Paper RAG retrieval explicitly optimize `@3`, `@5`, `@10`, MRR, evidence coverage, and source locator coverage instead of treating `@10` as the only practical retrieval signal.

## What Changes

- Add first-class `@3` and `@5` retrieval diagnostics and promotion checks alongside existing `@10` metrics.
- Introduce a Paper-specific hybrid retrieval policy that can combine dense retrieval, field retrieval, lightweight sparse lexical retrieval, visual retrieval, claim retrieval, and multi-query/RRF fusion.
- Strengthen ranking diagnostics so child, field, sparse, visual, graph, and rerank components remain observable in candidate metadata.
- Expand evidence graph behavior for table, figure, formula, and result-style questions so paired caption, referenced text, nearby context, and conclusion/result paragraphs are retrieved together.
- Preserve source locator metadata through expanded, parent, snippet, and supplemental chunks.
- Keep the optimization behind explicit policy switches so existing default retrieval behavior remains compatible.

## Capabilities

### New Capabilities
- `paper-rag-retrieval-optimization`: Paper-specific retrieval optimization covering top-k benchmark gates, hybrid/RRF candidate fusion, evidence graph expansion, and source locator preservation.

### Modified Capabilities
- `rag-kernel-candidate-aware-retrieval-metrics`: Retrieval metrics reports must expose `@3` and `@5` alongside `@10` for Paper RAG promotion and diagnostics.

## Impact

- Affected code:
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/paper_policy.py`
  - `business/research/rag/evaluation/paper_evidence_eval.py`
  - `business/research/rag/evaluation/paper_benchmark_suite.py`
  - Paper RAG retrieval tests under `tests/business/research/rag/`
- No breaking changes to default retrieval policy.
- No new network dependency is required for V1; stronger neural rerankers can be plugged in later through existing reranker ports.
