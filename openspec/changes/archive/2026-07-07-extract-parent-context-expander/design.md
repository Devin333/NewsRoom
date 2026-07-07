## Context

`ResearchRetriever` still contains all context expansion logic. Parent context expansion is one of the largest blocks and already has strong tests for long parent snippets, reranker-assisted ordering, per-intent budgets, result-heading preference, and reranker failure fallback. Extracting this block first reduces `paper_retriever.py` while keeping table/formula/cross-reference expansion untouched.

## Goals / Non-Goals

**Goals:**

- Introduce an `expanders` package with a small base protocol and a concrete `ParentContextExpander`.
- Move parent candidate discovery, scoring, rerank-assisted ranking, token budgeting, snippet generation, and parent metadata construction into `parent.py`.
- Keep `ResearchRetriever.retrieve()` parent output and metrics unchanged.
- Add module-level tests for parent expander behavior while preserving existing retriever integration tests.

**Non-Goals:**

- Do not move table, formula, figure, or cross-reference expansion in this slice.
- Do not change parent scoring weights, thresholds, budget logic, or snippet windows.
- Do not change the `RetrievalResult` contract.
- Do not introduce the final expander registry beyond the minimal protocol needed by this module.

## Decisions

- **Expander receives ports explicitly:** `ParentContextExpander` receives `chunk_store`, `policy`, and optional base reranker. This mirrors the current retriever dependencies without importing `ResearchRetriever`.
- **Parent-specific helpers move together:** `_ParentCandidate`, parent score helpers, token estimation, snippet anchoring, and source locator preservation move to `expanders/parent.py` because they are part of parent expansion semantics.
- **Shared metadata behavior is preserved locally:** Parent expansion still preserves source locators inherited from child chunks. Other expanders keep their current helper until later extraction.
- **Metrics shape remains identical:** `expand()` returns `(parent_chunks, metrics)` so `ResearchRetriever` can keep the same metadata assembly.

## Risks / Trade-offs

- **Some helper duplication may exist temporarily** -> Shared expansion metadata helpers will be consolidated after table/formula/cross-ref expanders move out.
- **Reranker ownership overlaps with `RerankCascade`** -> Parent rerank is expander-specific context ranking, so it stays in the parent expander for now.
