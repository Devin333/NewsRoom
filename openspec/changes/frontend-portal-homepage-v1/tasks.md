## 1. OpenSpec

- [x] 1.1 Create proposal, design, specs, and tasks for `frontend-portal-homepage-v1`.
- [x] 1.2 Validate `frontend-portal-homepage-v1` with `openspec validate --strict`.

## 2. Portal Homepage

- [x] 2.1 Add server-side homepage data aggregation from existing real loaders with per-module degraded states.
- [x] 2.2 Replace Portal `/` with the new homepage UI using the `/papers` editorial visual direction.
- [x] 2.3 Ensure homepage links cover AI News, Project Radar, Paper Radar, Community Pulse, Evidence Graph, and Reports.

## 3. Navigation, Routes, And Auth

- [x] 3.1 Update Portal navigation and i18n labels for Trending Papers, Tasks, Methods, and Community Buzz.
- [x] 3.2 Add `/community` to Portal route boundaries.
- [x] 3.3 Make Portal `/` public while keeping other Portal routes protected and Admin `/` protected.
- [x] 3.4 Change Portal post-login default to `/`.
- [x] 3.5 Render an Evidence Graph MVP for `/topics?view=evidence-graph`.

## 4. Legacy Dashboard Cleanup

- [x] 4.1 Delete the unused `/` dashboard page-content chain.
- [x] 4.2 Remove dashboard-only feature, lib, type, and API route code after confirming no remaining references.
- [x] 4.3 Update or remove tests that only cover the deleted dashboard surface.

## 5. Validation

- [x] 5.1 Run frontend lint, tests, and build.
- [x] 5.2 Verify `DashboardHomePage` is not used by `/` and Portal navigation does not expose old dashboard semantics.
- [x] 5.3 Commit the completed change.
