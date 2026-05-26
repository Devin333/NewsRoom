## Why

NewsRoom Portal currently still lets the root route render the legacy dashboard surface, while `/papers` has already established the intended reader-facing research product direction. This change makes `/` the public front door for AI news, papers, projects, community signals, evidence, and reports, with clear separation from Operations Studio.

## What Changes

- Replace the Portal root page with a reader-facing homepage based on the `/papers` editorial UI language.
- Show first-class module entries for AI News, Project Radar, Paper Radar, Community Pulse, Cross-board Evidence Graph, and Reports / Briefings.
- Build homepage counts and highlights from existing real server data loaders, with explicit degraded or empty states when data is unavailable.
- Make Portal `/` public while keeping other content routes protected by the existing session boundary.
- Update Portal navigation so Papers contains only Trending Papers, Tasks, and Methods, and Community Buzz points to `/community`.
- Remove the old dashboard homepage chain and dashboard-only dead code once `/` no longer uses it.

## Capabilities

### New Capabilities
- `frontend-portal-homepage`: Reader-facing Portal homepage, module entry cards, route/auth boundaries, and navigation behavior for the new front door.

### Modified Capabilities
None.

## Impact

- Affected frontend code: root page, Portal homepage components/data aggregation, navigation config/i18n, middleware, login defaults, topic evidence view behavior, and tests.
- Removes legacy dashboard homepage components, data layer, BFF route, dashboard types, and their tests when no remaining references exist.
- No backend API, database, workflow runtime, or new runtime dependency changes are required.
