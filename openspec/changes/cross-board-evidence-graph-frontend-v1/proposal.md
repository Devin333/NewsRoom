## Why

PRD-07 requires `/topics?view=evidence-graph` to explain why a technology trend matters by connecting papers, projects, news, community discussion, and reports. The current route only summarizes module counts, so it does not provide a topic-level evidence chain, scoring, node inspection, or API contract.

## What Changes

- Add a reader-facing Cross-board Evidence Graph page under the existing `/topics?view=evidence-graph` route.
- Add typed graph models, scoring, timeline, node detail, and related report payloads for the Portal frontend.
- Add Next BFF routes for graph search, node detail, and topic timeline.
- Build graph data from existing real NewsRoom loaders for AI News, Project Radar, Paper Radar, Community Pulse, and Reports.
- Keep homepage navigation pointing to `/topics?view=evidence-graph` and align the module description with PRD-07.
- Update PRD-07 status and tests for the completed frontend slice.

## Capabilities

### New Capabilities
- `frontend-cross-board-evidence-graph`: Reader-facing evidence graph page, BFF APIs, typed payloads, scoring, and homepage entry behavior.

### Modified Capabilities
None.

## Impact

- Affected frontend code: evidence graph types, data service, BFF route handlers, `/topics` route branch, Portal evidence graph page, homepage module copy, and tests.
- Affected docs: PRD-07 status/runtime wording and OpenSpec change artifacts.
- No Python backend API, database migration, realtime graph database, or new runtime dependency is required.
