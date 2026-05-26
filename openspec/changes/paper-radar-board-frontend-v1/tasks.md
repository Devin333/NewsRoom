## 1. OpenSpec

- [x] 1.1 Create proposal, design, specs, and tasks for `paper-radar-board-frontend-v1`.
- [x] 1.2 Validate `paper-radar-board-frontend-v1` with `openspec validate --strict`.

## 2. Data And API

- [x] 2.1 Remove bundled catalog paper fallback from runtime public paper list loading while preserving backend/cache/artifact sources.
- [x] 2.2 Add real fallback filtering and sorting to `/api/papers` for PRD query parameters.
- [x] 2.3 Add derived task/method API fallback based on taxonomy plus real paper counts.
- [x] 2.4 Add real-data fallback for `/api/papers/:paperId`.

## 3. Paper Radar UI

- [x] 3.1 Add Portal homepage Research Entries for Trending Papers, Tasks, and Methods.
- [x] 3.2 Keep `/papers` editorial UI stable and move remaining hard-coded UI copy into i18n.
- [x] 3.3 Strengthen `/papers/tasks` and task detail views with real-derived counts, latest papers, implementations, and empty states.
- [x] 3.4 Strengthen `/papers/methods` and method detail views with real-derived representative papers, implementations, and empty states.
- [x] 3.5 Add related project/news/community/evidence sections to the paper detail drawer with empty states.

## 4. Documentation And Tests

- [x] 4.1 Update PRD-05 status and runtime data wording.
- [x] 4.2 Update unit tests for real-data fallback and task/method empty states.
- [x] 4.3 Update Playwright navigation coverage for Paper Radar routes, drawer deep-link, and homepage entries.

## 5. Validation And Commit

- [x] 5.1 Run frontend typecheck, lint, tests, and build.
- [x] 5.2 Run targeted Playwright navigation spec.
- [x] 5.3 Commit the completed change.
