## Context

`ResearchRetriever` currently performs base cross-encoder scoring and structured field rerank scoring through private methods. These methods are execution-stage logic, not query planning or recall. PRD 16 expects a `rerank.py` stage so the future `RetrievalPipeline` can call reranking independently from recall and context expansion.

## Goals / Non-Goals

**Goals:**

- Introduce `RerankCascade` as the owner of candidate-level base and field rerank scoring.
- Preserve the exact current fallback semantics:
  - no reranker or disabled intent returns semantic scores;
  - reranker exceptions fall back to semantic scores or empty field scores;
  - malformed score counts fall back safely.
- Keep `ResearchRetriever` responsible for final child score fusion in this slice.
- Add focused tests for rerank behavior without requiring a vector store.

**Non-Goals:**

- Do not move parent context rerank or table context rerank in this slice.
- Do not change rerank thresholds, intent scopes, or scoring weights.
- Do not introduce cross-encoder model loading or new dependencies.
- Do not build the final `RetrievalPipeline` yet.

## Decisions

- **Cascade owns score production only:** `RerankCascade.base_scores()` and `field_rerank_scores()` return primitive scores/maps. The existing retriever still applies threshold filtering and child score fusion, preserving behavior.
- **Field passage formatter moves with rerank:** `_field_rerank_passage` becomes `field_rerank_passage` in `rerank.py` because it is part of structured field reranker input construction.
- **Policy remains injected:** The cascade receives `RetrievalPolicy` plus optional reranker ports and delegates enabled checks to policy methods, so tuned policy behavior stays centralized.

## Risks / Trade-offs

- **Rerank stage is not fully complete** -> Parent/table context rerank remains in expanders until expander extraction, but candidate reranking now has a clear module boundary.
- **Logging behavior can drift** -> The cascade logs the same warning conditions and returns the same fallback shapes.
