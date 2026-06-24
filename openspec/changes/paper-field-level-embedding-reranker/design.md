## Context

The previous `paper-field-aware-retrieval-scoring` change added deterministic lexical scores for `title`, `abstract`, `caption`, `equation`, and `body`. Those scores are useful for explanation and tuning, but they cannot capture semantic matches such as "what do the experiments show" matching a table caption or conclusion paragraph that uses different wording.

The current production retrieval path is:

1. Search the main paper chunk vector index.
2. Optionally rerank base candidates.
3. Score candidates with deterministic field score and position.
4. Expand parents, references, table context, and visual hits.
5. Convert returned chunks into evidence packs.

This change keeps that path intact and adds an optional field-level semantic path beside it.

## Goals / Non-Goals

**Goals:**

- Extract normalized field text from existing `PaperChunk` data.
- Index field vectors without changing `PaperChunk` persistence schema.
- Use query intent to decide which fields to search and how to weight them.
- Merge field hits with base vector candidates by `chunk_id`.
- Use a structured field passage for optional reranking.
- Produce explainable `child_final_score` metadata for every returned child chunk.
- Keep deterministic fallback behavior when the field index or field reranker is unavailable.

**Non-Goals:**

- Rewriting the parser, OCR, Nougat, Surya, or chunking logic.
- Adding a required new embedding provider.
- Training a new ranking model.
- Making multimodal image embedding mandatory.
- Replacing parent, table, reference, or visual expansion.

## Decisions

### Field text is derived from `PaperChunk`

Field text extraction lives in `business/research/rag/field_text.py`. It reads existing chunk fields and metadata:

- `title`: `section_title`
- `abstract`: abstract chunk content
- `caption`: caption metadata and caption blocks in figure/table content
- `equation`: `formula_latex`, `formula_description`, and formula chunk content
- `body`: chunk content

This keeps indexing independent from parser internals and avoids a persistent schema migration.

### Field vectors use a separate collection

The infrastructure adapter stores one vector document per field:

```text
document_id = <chunk_id>:<field_name>
paper_id
chunk_id
field_name
field_text
source_locator
```

A separate field collection avoids mixing whole-chunk vectors with field vectors that have different text granularity. It also lets operations delete/reindex all fields for a paper without touching unrelated collections.

### Field retrieval is optional and merged by chunk id

`ResearchRetriever` receives an optional `field_index`. If it is absent or fails, retrieval falls back to the existing main chunk search plus deterministic field scoring. If it is present, the retriever searches intent-selected fields, resolves returned chunks with `ChunkStorePort.get_chunk`, and merges best field scores into the candidate's metadata.

### Field reranking is explicit

`ResearchRetriever` receives an optional `field_reranker`. It can be the same concrete cross-encoder as the base reranker, but it is wired as a separate dependency so tests and lightweight call sites do not unexpectedly pay reranker cost. The structured passage includes field labels so the reranker can compare the query against title, abstract, caption, equation, and body separately.

### Score fusion has final and fallback modes

When field embedding and field reranking signals exist, child ranking uses:

```text
child_final_score =
  semantic_score * 0.45
+ field_embedding_score * 0.25
+ field_rerank_score * 0.20
+ position_score * 0.05
+ graph_score * 0.05
```

When those semantic field signals are not available, child ranking uses:

```text
child_final_score =
  semantic_score * 0.60
+ deterministic_field_score * 0.25
+ position_score * 0.10
+ graph_score * 0.05
```

The existing lexical `field_score` remains available in both modes as a fallback and debugging signal.

## Risks / Trade-offs

- Field index can increase vector storage volume by up to five documents per chunk -> only non-empty fields are indexed and the collection can be deleted per paper.
- Field reranking can add latency -> it is optional and limited to returned/over-fetched candidates.
- Field vector hits can introduce duplicates -> candidates are merged by `chunk_id` and best per-field scores are retained.
- Query intent can choose imperfect fields -> the plan always includes `body` for robustness and deterministic scoring remains available.
- Graph score can be weak early on -> it starts as transparent metadata-derived scoring and can later consume richer graph edges.
