## Context

Table context expansion is currently mixed into `ResearchRetriever`. It has two related behaviors: adding supplemental table chunks into child results, and expanding table chunks into reference context. This slice extracts only the latter because supplemental table hits call the retriever's child scoring logic and should move after child scoring is isolated.

## Goals / Non-Goals

**Goals:**

- Move table ref context expansion into `TableContextExpander`.
- Preserve `table_nearby_context`, `table_body_reference`, `table_row_group_parent`, `table_parent_context`, and `table_result_context` behavior.
- Preserve table result context reranking and metadata.
- Keep retriever metadata counts unchanged.

**Non-Goals:**

- Do not move `_supplemental_table_hits` yet.
- Do not change table/result heuristics or reranker thresholds.
- Do not change child scoring or table chunk recall.

## Decisions

- **Question-aware expander:** `expand(chunks, request, route)` receives the same request and route objects because result-context expansion depends on both question text and intent.
- **Reranker remains optional:** The expander receives the optional base reranker and follows the same fallback behavior as the retriever did.
- **Local helper duplication is accepted temporarily:** Result-question heuristics remain duplicated until formula/table structural interleave is moved and shared helper modules can be introduced cleanly.

## Risks / Trade-offs

- **Partial table behavior split** -> Supplemental table child injection remains in retriever, but table reference context is now isolated and tested.
- **Helper duplication** -> This is intentional for the transition; final cleanup can consolidate result-question predicates.
