## Why

PRD 16 targets a retrieval pipeline with a dedicated rerank stage, but base and field rerank score calculation still lives inside `ResearchRetriever`. Extracting this into `RerankCascade` reduces retriever responsibilities while preserving the tuned ranking behavior.

## What Changes

- Add `business.research.rag.retrieval.rerank` with `RerankCascade`.
- Move base reranker scoring and structured field reranker scoring out of `ResearchRetriever`.
- Preserve existing fallback behavior when rerankers are missing, fail, or return malformed score counts.
- Keep parent/table context rerank inside the existing expander logic for now.
- Add unit tests for base score fallback, reranker failure fallback, malformed-score fallback, and field rerank scoring.

## Capabilities

### New Capabilities

- `paper-rag-retrieval-rerank-cascade`: Paper RAG retrieval can run candidate reranking through a dedicated rerank stage before final child scoring.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/rerank.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/__init__.py`
  - retrieval unit tests
- No intended behavior change to ranking scores, threshold filtering, returned chunks, or metadata.
