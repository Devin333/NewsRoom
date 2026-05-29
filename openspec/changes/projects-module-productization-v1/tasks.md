## 1. OpenSpec

- [x] 1.1 Create proposal, design, specs, and tasks for `projects-module-productization-v1`.
- [x] 1.2 Validate `projects-module-productization-v1` with `openspec validate --strict`.

## 2. Backend Domain And Services

- [x] 2.1 Add `business/projects` models, DTOs, enums, repositories, Project Radar bridge, and deterministic service modules.
- [x] 2.2 Implement Hot/Rising ranking, Tools, Cases, Lab, Collections, Watchlist, and Evolution services using real project data plus local mutable state.
- [x] 2.3 Add `interfaces/services/project_service.py` as the public application service boundary.

## 3. Backend API And Docs

- [x] 3.1 Add and register `interfaces/api/routers/projects.py`.
- [x] 3.2 Wire `ProjectApplicationService` through API dependencies, auth permissions, router tags, and app factory injection.
- [x] 3.3 Update `docs/api/openapi.json` and `docs/api/README.md`.

## 4. Frontend

- [x] 4.1 Add Projects API client/types for `/api/v1/projects/*`.
- [x] 4.2 Replace `/projects` with the Projects product home while preserving `/tech/repos` and `/projects/[slug]`.
- [x] 4.3 Add `/projects/hot`, `/projects/rising`, `/projects/tools`, `/projects/cases`, `/projects/lab`, `/projects/collections`, and `/projects/watchlist` pages.

## 5. Tests And Validation

- [x] 5.1 Add backend domain, service, and API tests.
- [x] 5.2 Add frontend client/page tests for core module rendering and compatibility.
- [x] 5.3 Run compile, backend tests, OpenSpec validation, frontend tests, and frontend typecheck.
- [x] 5.4 Commit only this change's files.
