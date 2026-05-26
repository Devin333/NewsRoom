## Why

The existing `/tech/repos` surface has a real Project Radar data path, but it still behaves like an early project list and contains visible mojibake in user-facing copy. PRD-04 requires a reader-facing Project Radar Board that matches the Portal, AI News, and Papers front-stage experience while keeping runtime data grounded in backend or local artifacts.

## What Changes

- Upgrade `/tech/repos` into the Project Radar Board with an editorial hero, period/topic/language/maturity/sort/search controls, facets, a trending project treatment, project stream, and explicit empty/degraded states.
- Keep the existing backend/artifact data loading path for `project_radar-productized-board`; do not introduce bundled mock projects as runtime business data.
- Preserve `/api/projects` response envelope while adding PRD-friendly query aliases for `period`, `topic`, `maturity`, `sort`, `limit`, and `cursor`.
- Add a Project Detail Drawer on `/tech/repos?project=<slug>` while preserving `/projects` and `/projects/[slug]` compatibility routes.
- Align public project fields, category labels, maturity handling, relation counts, and visible copy with PRD-04.
- Update PRD-04 status and MVP data-source language after implementation.

## Capabilities

### New Capabilities
- `project-radar-board-frontend`: Reader-facing Project Radar Board list, filters, real-data states, trending treatment, project details, and PRD alignment.

### Modified Capabilities
None.

## Impact

- Affected frontend code: `/tech/repos`, `/projects`, `/projects/[slug]`, `/api/projects`, project mapper/types/API client, project components, project tests, navigation e2e coverage, and PRD-04 docs.
- No backend API, database, workflow runtime, GitHub OAuth, or new runtime dependency changes are required.
