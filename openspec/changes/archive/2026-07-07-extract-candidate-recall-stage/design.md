## Context

Most recall channels already exist as modules, but `ResearchRetriever` still coordinates them directly and owns the hybrid candidate fusion logic. This blocks a future `RetrievalPipeline` because the first pipeline stage has no stable object boundary.

## Goals / Non-Goals

**Goals:**

- Extract candidate recall and hybrid fusion into a reusable stage.
- Preserve `candidates`, `field_hits`, `claim_hits`, `visual_hits`, `n_recalled`, `n_visual_recalled`, and `query_variants` semantics.
- Preserve sparse trace degradation behavior.
- Keep `retrieve()` metrics compatible.

**Non-Goals:**

- Do not change recall limits, query expansion, filters, or RRF scoring.
- Do not move reranking or context expansion in this slice.
- Do not introduce the final `RetrievalPipeline` class in this slice.

## Decisions

- **Stage owns channel instances:** The retriever already constructs channels. Passing them into the stage keeps this slice narrow and avoids reworking factories.
- **Stage returns structured result:** `CandidateRecallResult` makes downstream metrics explicit instead of recomputing hidden local variables.
- **Query variant helper moves with the stage:** It is part of recall planning/execution and is reported back for metrics.

## Risks / Trade-offs

- **Temporary private wrapper remains:** `ResearchRetriever._search_text_candidates` and related methods are removed, but `retrieve()` still orchestrates later rerank/context stages until final pipeline extraction.
- **Metric drift risk** -> Existing `test_retriever.py` plus focused stage tests verify query variants, hit counts, and hybrid fusion metadata.
