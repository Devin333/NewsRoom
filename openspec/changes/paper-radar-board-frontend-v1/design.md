## Overview

PRD-05 is implemented as a frontend alignment over the existing Paper Radar system. The work preserves the `/papers` editorial UI, adds missing homepage research entry affordances, and tightens data handling so runtime pages never invent public paper stream data.

## Data Source Policy

- `getPublishedPapers()` remains the canonical server loader for published papers.
- Source order is backend `/api/v1/papers`, tracked cache `frontend/data/papers/arxiv-papers.json`, local Paper Radar artifacts, then an empty result.
- Bundled catalog papers remain available for tests and taxonomy helpers only; they are not returned by runtime public paper list loaders.
- Task/method taxonomy may use `paperTasks` and `paperMethods` when backend task/method APIs are unavailable, but paper counts, latest papers, implementations, and related content are computed from real paper data.

## API And UI Shape

- `/api/papers` keeps the existing envelope and supports `q`, `period`, `sort`, `task`, `method`, `limit`, and `offset` against backend or real fallback data.
- `/api/papers/tasks` and `/api/papers/methods` keep their existing response keys while allowing derived taxonomy results when backend data is unavailable.
- `/api/papers/:paperId` falls back to real locally available paper data before returning a not-found error.
- The Portal homepage adds a Paper Radar research section with direct links to Trending Papers, Tasks, and Methods.
- Paper drawer related sections show real implementation, benchmark, project/news/community/evidence information where available and explicit empty states otherwise.

## Compatibility

Existing `Paper`, `PaperTask`, and `PaperMethod` fields remain valid. Optional PRD-compatible fields or view models may be added without replacing current reader, drawer, or tests contracts.
