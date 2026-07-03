## Context

After parent context expansion moved into `ParentContextExpander`, `ResearchRetriever` still owns cross-reference expansion. This block is smaller than table context expansion but includes several important source types: explicit chunk references, page visual related chunks, figure body references, formula explanation refs, and formula reverse refs.

## Goals / Non-Goals

**Goals:**

- Move cross-reference expansion into `CrossRefContextExpander`.
- Preserve first-level reference behavior and deduplication.
- Preserve expansion metadata fields produced by `_with_expansion_metadata`.
- Keep table result context expansion in `ResearchRetriever` for a later slice.

**Non-Goals:**

- Do not change which refs are followed or how many first-level refs are used.
- Do not change table context expansion.
- Do not change formula context scoring or child interleaving behavior.

## Decisions

- **Expander owns formula reverse scan:** Formula reverse context requires `list_chunks(paper_id)`, so the expander receives `ChunkStorePort` and performs the same scan currently done by the retriever.
- **Metadata helper is local:** Cross-ref expansion gets its own local expansion metadata helper to avoid importing private retriever functions.
- **Public contract is simple:** `expand(children, paper_id)` returns only the ref chunks list because metrics are already computed in `ResearchRetriever`.

## Risks / Trade-offs

- **Temporary helper duplication** -> Table/formula structural interleave still uses similar helper logic in `paper_retriever.py`; this will be consolidated when table/formula expanders move.
- **Cross-ref and formula interleave overlap** -> Existing dedupe behavior is preserved by keeping the same `seen` logic scoped to child chunks.
