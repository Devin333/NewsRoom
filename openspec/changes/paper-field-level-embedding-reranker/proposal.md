## Why

Research retrieval now has deterministic field scoring for title, abstract, caption, equation, and body text. That is explainable, but it still depends on lexical overlap, so field-sensitive questions can miss strong evidence when the user wording differs from the paper wording.

This change upgrades field-aware retrieval from a bounded lexical boost to a full field-level retrieval path: field text extraction, field vector search, intent-aware field selection, structured field reranking, score fusion, and observability.

## What Changes

- Add reusable field text extraction for `PaperChunk` objects.
- Add a field-level embedding index that stores one vector document per chunk field.
- Let `ResearchRetriever` merge field vector hits with base chunk hits by `chunk_id`.
- Add intent-aware field search plans for figure, table, formula, contribution, method, and result questions.
- Add optional structured field reranking using the existing reranker port.
- Fuse semantic, field embedding, field rerank, position, and graph scores into `child_final_score`.
- Preserve deterministic lexical field scoring as the fallback path when no field index or field reranker is configured.
- Expose field embedding, reranker, best field, graph score, and final score metadata through retrieval results and evidence packs.

## Capabilities

### New Capabilities
- `paper-field-level-embedding-reranker`: Defines field-level semantic retrieval, structured reranking, score fusion, and observability for research paper RAG.

### Modified Capabilities

## Impact

- Affects `business/research/rag/retriever.py`, `business/research/rag/retrieval_port.py`, field text utilities, research ports, vector storage adapters, pipeline/factory wiring, and focused RAG tests.
- Reuses existing vector store and reranker abstractions; no new external model dependency is required by the business layer.
- No parser, OCR, chunk schema, database schema, or PDF artifact migration is required.
