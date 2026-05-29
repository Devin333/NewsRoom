## Why

The new Projects PRD package defines a product module that is broader than the existing Project Radar Board. The repository already has real Project Radar runs/artifacts and a reader-facing `/projects` compatibility surface, but it does not yet expose a backend Projects domain, `/api/v1/projects/*` product API, or the Hot/Rising/Tools/Cases/Lab/Collections/Watchlist routes described by the PRD.

## What Changes

- Add `business/projects` as the Projects product domain, reusing Project Radar output as the initial real-data source rather than replacing it.
- Add `ProjectApplicationService` under `interfaces/services/project_service.py` and route all Projects HTTP APIs through it.
- Add `/api/v1/projects/*` endpoints for home, hot, rising, tools, cases, lab sessions, collections, watchlist, and interactions.
- Add frontend `/projects/*` routes for the PRD modules while preserving `/tech/repos` and `/projects/[slug]` compatibility.
- Persist Lab, Watchlist, and interaction runtime state locally under `.newsroom/projects` unless a caller injects another repository.
- Update OpenAPI documentation and tests for the new product API and frontend routes.

## Capabilities

### New Capabilities
- `projects-module-productization`: Projects product API, product DTOs, rankings, tools, cases, lab, collections, watchlist, interactions, and frontend module routes.

### Modified Capabilities
- Existing Project Radar frontend compatibility remains intact but `/projects` becomes the Projects product home rather than only a Project Radar alias.

## Impact

- Affected backend code: `business/projects`, `interfaces/services/project_service.py`, `interfaces/api/routers/projects.py`, API dependency/app/router registration, OpenAPI export docs, and tests.
- Affected frontend code: project types/client/data-source compatibility, `/projects` route tree, project module components, and route/client tests.
- No new third-party backend dependency, no database migration requirement, no source scraping bypass, and no fake runtime project data.
