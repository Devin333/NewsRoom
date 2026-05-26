## 1. OpenSpec

- [x] 1.1 Create proposal, design, specs, and tasks for `ai-news-board-frontend-v1`.
- [x] 1.2 Validate `ai-news-board-frontend-v1` with `openspec validate --strict`.

## 2. Data And API

- [x] 2.1 Remove bundled mock news as runtime fallback from server data loading.
- [x] 2.2 Add query alias handling for `period`, `source`, and PRD sort values.
- [x] 2.3 Update news data/API tests for real-data empty states and aliases.

## 3. AI News Board UI

- [x] 3.1 Upgrade `/news` to the PRD-03 board layout with hero, filters, facets, top story, and stream.
- [x] 3.2 Add top story, relation counts, and real cluster rendering only when supported by data.
- [x] 3.3 Fix visible mojibake and hardcoded copy in list components.

## 4. News Detail

- [x] 4.1 Fix visible mojibake and hardcoded copy in detail components.
- [x] 4.2 Add related papers/projects/community sections with empty states.

## 5. Documentation

- [x] 5.1 Verify PRD-01 remains aligned and unchanged except for prior completion state.
- [x] 5.2 Update PRD-03 status and MVP data-source language.

## 6. Validation

- [x] 6.1 Run OpenSpec validation.
- [x] 6.2 Run frontend typecheck, lint, tests, and build.
- [x] 6.3 Run Playwright navigation spec for `/news` and related routes.
- [x] 6.4 Commit the completed change.
