## Context

`_supplemental_table_hits` is the last table-specific child injection path still owned by `ResearchRetriever`. It searches table chunks only when result-style questions return no table child, then applies child scoring and adds `supplemental_reason`.

## Goals / Non-Goals

**Goals:**

- Move supplemental table hit injection into a focused expander.
- Reuse `ChildCandidateScorer` instead of calling a retriever private method.
- Reuse the existing result-context predicate from `table_context.py`.
- Preserve error handling and dedupe behavior.

**Non-Goals:**

- Do not change the supplemental table search query, limit, filters, or metadata.
- Do not merge supplemental table injection with `TableContextExpander` yet.
- Do not introduce the final retrieval pipeline in this slice.

## Decisions

- **Expander returns extra chunks only:** This matches the current `_supplemental_table_hits` behavior, where `retrieve()` extends child chunks with returned supplemental hits.
- **Scorer dependency is explicit:** The expander owns a `ChildCandidateScorer(policy)` so child score metadata remains identical.
- **Table predicate is local:** The expander uses its own `_is_table_chunk` helper for now, matching migration style in other expanders.

## Risks / Trade-offs

- **Temporary duplication of table detection** -> Several expanders currently have local table helpers during migration. Consolidation can happen after the expander set stabilizes.
- **Behavior drift risk** -> Existing `test_retriever.py` and new focused tests guard the no-table-yet and table-already-present cases.
