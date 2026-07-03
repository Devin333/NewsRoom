## Context

The pipeline currently performs two concerns after recall: it asks `RerankCascade` for scores and then directly scores/fuses/sorts child chunks. `ChildCandidateScorer` already owns per-child scoring, and `VisualRecallChannel` owns visual score fusion, so the remaining logic is orchestration for the child ranking stage.

## Goals / Non-Goals

**Goals:**

- Introduce a reusable child ranking stage.
- Preserve base reranker threshold fallback behavior.
- Preserve field rerank score use and visual fusion behavior.
- Return structured ranking outputs needed by metrics: scored candidates, child chunks, filter count, reranker enabled flags, and field rerank scores.

**Non-Goals:**

- Do not change ranking weights, thresholds, or visual fusion formulas.
- Do not move structural/table supplemental expansion in this slice.
- Do not introduce a declarative stage registry yet.

## Decisions

- **Stage receives the rerank cascade, scorer, and visual channel:** These are already constructed by `ResearchRetriever`; passing them in mirrors the existing pipeline extraction style.
- **Structured result over tuple soup:** `ChildRankingResult` names the metrics-facing values that downstream code needs.
- **Request factory stays with ranking stage:** Visual-only fusion needs a synthetic request for child scoring with the same paper/question/current section. Keeping the factory here avoids leaking that detail into the pipeline.

## Risks / Trade-offs

- **Stage still depends on policy and route shape** -> This is acceptable because child ranking is intent-aware by design.
- **Pipeline still passes several fields to metrics** -> The metrics builder preserves the current report contract. Later a stage context object can reduce parameter count.
