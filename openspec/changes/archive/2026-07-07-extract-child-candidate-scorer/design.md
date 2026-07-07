## Context

After channel, planner, rerank, and expander extraction, `ResearchRetriever` still contains a large scoring block that mutates child chunk metadata and returns the final child score. Supplemental table retrieval also calls the same private scorer, so extracting it first creates a cleaner dependency for the next expander slice.

## Goals / Non-Goals

**Goals:**

- Move child candidate scoring into `ChildCandidateScorer`.
- Preserve every existing child scoring metadata key.
- Preserve field lexical scoring, field embedding/rerank fusion, citation boosts, formula sparse boosts, element label boosts, graph score, route match score, and position score.
- Keep policy normalization helpers available to `RetrievalPolicy`.

**Non-Goals:**

- Do not change score weights or scoring formulas.
- Do not move supplemental table hits yet.
- Do not introduce the final `RetrievalPipeline` in this slice.

## Decisions

- **Scorer takes policy at construction:** This mirrors the existing retriever-owned behavior and avoids scattering policy lookups.
- **Request and route are duck-typed:** `scoring.py` avoids importing `RetrievalRequest` or `RetrievalRoute` from `paper_retriever.py`, preventing a circular dependency while keeping the production contract unchanged.
- **Normalization helpers move with scoring:** `RetrievalPolicy` imports the helper functions from `scoring.py`, so policy behavior stays centralized with scoring logic.
- **Retriever wrapper remains temporarily:** `_score_child_candidate` stays as a small delegating method until a later pipeline extraction removes the legacy entrypoint.

## Risks / Trade-offs

- **More helper exports during migration** -> Some helpers are exported from `scoring.py` for policy and tests. They can be tightened after `paper_retriever.py` becomes a thin entrypoint.
- **Behavior drift risk** -> Focused tests assert key metadata and existing `test_retriever.py` remains the parity guard.
