## Why

Paper Radar is already the frontend visual reference for NewsRoom, but the PRD-05 surface still needs a formal contract and final alignment. The homepage, navigation, tasks, methods, APIs, and paper detail drawer should consistently present a reader-facing research intelligence board using real paper data instead of bundled business mock data.

## What Changes

- Add a Paper Radar Board frontend contract covering `/papers`, `/papers/tasks`, `/papers/methods`, task/method detail routes, and the Portal homepage Paper Radar entry points.
- Keep `/papers` as the editorial research board with period, search, sort, domain sidebar, stream, and paper detail drawer.
- Make runtime paper data source priority explicit: backend, tracked cache, local artifacts, then empty/degraded state; bundled catalog papers must not be used as public stream fallback.
- Use local task/method catalog only as taxonomy when backend task/method APIs are unavailable, with counts and related content derived from real paper data.
- Add PRD-05 homepage Research Entries and update PRD documentation to implemented/aligned status.

## Capabilities

### New Capabilities

- `paper-radar-board-frontend`: Reader-facing Paper Radar board, real-data fallback behavior, task/method boards, detail views, and homepage research entry integration.

### Modified Capabilities

- None.

## Impact

- Frontend paper data loaders, `/api/papers*` BFF routes, Paper Radar components, Portal homepage data/UI, paper i18n copy, unit/E2E tests, OpenSpec artifacts, and PRD-05 documentation.
