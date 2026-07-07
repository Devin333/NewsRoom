## Context

Visual recall combines a visual vector store with text candidates. The existing helpers already separate low-level fusion math in `paper_visual_retrieval.py`, but `ResearchRetriever` still owns visual store search and chunk-ranking adaptation.

## Goals / Non-Goals

**Goals:**

- Move visual search and visual hit adaptation into a channel class.
- Preserve current warning-and-empty behavior when visual retrieval fails.
- Preserve `with_retrieval_scores` metadata and visual fusion behavior.

**Non-Goals:**

- Do not change when visual recall is enabled; `ResearchRetriever` still gates it by figure intent.
- Do not change visual fusion weights or child final scoring.
- Do not move figure/table context expansion in this slice.

## Decisions

- **Channel owns fusion source adaptation:** `VisualRecallChannel.fuse_scores(...)` wraps `fuse_visual_retrieval_scores` with configured weights and store lookup.
- **Retriever owns final child scoring:** The retriever still calls `_score_child_candidate` after visual fusion because final child scoring combines route, field rerank, position, graph, and other policy signals.

## Risks / Trade-offs

- The channel exposes chunk-shaped compatibility helpers during transition. This remains temporary until the final retrieval pipeline consumes `RankedHit` end to end.
