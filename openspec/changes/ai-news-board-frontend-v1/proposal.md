## Why

The existing `/news` surface has a functional list and detail flow, but it still reads like an early reader portal list rather than the PRD-03 AI News Board. It also contains visible mojibake in hardcoded copy and still falls back to bundled mock business data at runtime when real board output is unavailable.

## What Changes

- Upgrade `/news` into the AI News Board front-end module with an editorial hero, filter bar, source/topic facets, top story treatment, news rows, and explicit empty/degraded states.
- Keep the existing backend/artifact data loading path for `ai_news-productized-board`, but stop using bundled mock news as runtime business data.
- Preserve `/api/news` response envelope while adding PRD-friendly query aliases for `period`, `source`, and `sort`.
- Improve `/news/[id]` detail presentation for evidence and related papers/projects/community references, with clear empty states.
- Fix visible hardcoded mojibake in the AI News list/detail UI.
- Update PRD-03 status and MVP notes after implementation.

## Capabilities

### New Capabilities
- `ai-news-board-frontend`: Reader-facing AI News Board list, filters, real-data states, top story, news rows, details, and PRD alignment.

### Modified Capabilities
None.

## Impact

- Affected frontend code: `/news`, `/news/[id]`, news components, news filters/API parsing, news server data fallback behavior, tests, and PRD-03 docs.
- No backend API, database, workflow runtime, or new runtime dependency changes are required.
