## Why

Research parent-child retrieval already limits parent context volume with count budgets, token budgets, snippets, intent-specific budgets, and optional parent reranking. However, parent ordering is still mostly implicit: parents follow child rank unless a reranker is available, and section heading relevance is only indirectly included in reranker passages.

This makes ranking harder to explain and tune. A parent can be included because its child matched strongly, because the parent itself is relevant, because the section heading fits the query intent, or because it is near the reader's current section, but those factors are not exposed as one final score.

## What Changes

- Add explicit parent scoring weights for child relevance, parent relevance, section heading relevance, and position.
- Compute and persist `parent_final_score` plus score breakdown metadata for every expanded parent context chunk.
- Use `parent_final_score` as the primary parent candidate ordering signal, with child rank as deterministic tie-break.
- Add intent-specific score weights so method, result, table, and comparison questions can prioritize different signals.
- Expose parent scoring metrics in retrieval metadata for inspection and tuning.

## Capabilities

### New Capabilities
- `paper-parent-context-explicit-scoring`: Defines explainable parent context ranking for research paper RAG.

### Modified Capabilities
- `research-runtime`: Research retrieval must expose why parent context was ranked and included.

## Impact

- Affects `business/research/rag/retriever.py`, `business/research/rag/retrieval_port.py`, and focused RAG tests.
- No parser, vector store, database, or persistent chunk schema migration is required.
- Existing parent budget, snippet, and fallback behavior remains in place.
