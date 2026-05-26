## 1. OpenSpec

- [x] 1.1 Create proposal, design, specs, and tasks for `project-radar-board-frontend-v1`.
- [x] 1.2 Validate `project-radar-board-frontend-v1` with `openspec validate --strict`.

## 2. Data And API

- [x] 2.1 Extend Project Radar types for PRD categories, maturity, scores, canonical repo metadata, and relation counts while preserving compatibility fields.
- [x] 2.2 Add PRD query alias handling for `period`, `topic`, `maturity`, `sort`, `limit`, and `cursor`.
- [x] 2.3 Update mapper logic for category aliases, timestamp filtering, maturity derivation, activity sorting, metrics, facets, notices, and no-mock empty states.
- [x] 2.4 Update project data/API tests for aliases, maturity behavior, and real-data empty states.

## 3. Project Radar Board UI

- [x] 3.1 Upgrade `/tech/repos` to the PRD-04 board layout with hero, filters, facets, trending project, project stream, clusters, and explicit empty/degraded states.
- [x] 3.2 Add PRD-complete project row/card content: repo metadata, stars, star delta, updated time, topics, maturity state, and relation counts.
- [x] 3.3 Fix visible mojibake and hardcoded copy in Project Radar list components.

## 4. Project Detail

- [x] 4.1 Add `/tech/repos?project=<slug>` Project Detail Drawer with URL-preserving close behavior.
- [x] 4.2 Reuse detail content between drawer and `/projects/[slug]`, including related papers/news/community and evidence empty states.
- [x] 4.3 Update project detail tests for drawer and shareable detail behavior.

## 5. Documentation

- [x] 5.1 Update PRD-04 status to implemented/aligned.
- [x] 5.2 Replace runtime mock MVP language with backend/artifact data plus empty-state behavior.

## 6. Validation

- [x] 6.1 Run OpenSpec validation.
- [x] 6.2 Run frontend typecheck, lint, tests, and build.
- [x] 6.3 Run Playwright navigation coverage for `/tech/repos`, project drawer/detail, `/projects`, and Portal entry.
- [x] 6.4 Commit the completed change.
