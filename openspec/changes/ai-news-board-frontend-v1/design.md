## Context

The current frontend already has `/news`, `/news/[id]`, `/api/news`, and `getNewsListResult`. Data loading first tries backend runs/artifacts for `ai_news-productized-board`, then local artifacts, then bundled mock news. PRD-03 requires a front-stage AI News Board, not a backend table or mock-only MVP.

## Goals / Non-Goals

**Goals:**
- Make `/news` feel like the same reader-facing research product as `/papers`.
- Use real backend/artifact AI News data when available.
- Show explicit empty/degraded states when real data is missing.
- Preserve existing route and API compatibility.
- Fix visible mojibake in AI News UI.

**Non-Goals:**
- Adding a new backend endpoint or persistence model.
- Implementing realtime feeds, personalization, or generated summaries.
- Implementing an in-page detail drawer in v1.
- Fabricating clusters or related objects that are not present in data.

## Decisions

- Keep `/news/[id]` as the v1 detail experience instead of adding a drawer.
- Treat bundled mock news as test/demo data only, not runtime fallback for the board.
- Map PRD query aliases into existing filter fields:
  - `period=daily|weekly|monthly|all` -> existing `dateRange`.
  - `source=<sourceType>` -> existing `sourceType`.
  - `sort=top|trending|newest` -> existing sort fields.
- Derive Top Story from filtered results using existing scores and source credibility; if no item exists, render a board-level empty state.
- Render Cluster Card only when real records share topic IDs or related evidence enough to form a cluster.

## Risks / Trade-offs

- Removing mock runtime fallback can make local `/news` empty until backend/artifact data exists; this is intentional to avoid fake business data.
- Current types use existing category/source conventions rather than the exact PRD enum names; aliases keep user-facing behavior aligned without a breaking DTO rewrite.
