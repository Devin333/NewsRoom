## Context

The PRD package asks for Projects to be a productized upgrade of Project Radar. Current code already includes `business/boards/project_radar`, real `.newsroom/runs/*project_radar*` artifacts, `/tech/repos`, `/projects`, `/projects/[slug]`, and a frontend artifact mapper. The backend lacks a product domain and `/api/v1/projects` endpoints.

## Goals / Non-Goals

**Goals:**
- Create a cohesive Projects domain model and application service.
- Use existing Project Radar artifacts as the initial true project corpus.
- Provide PRD-aligned APIs and frontend pages for Hot, Rising, Tools, Cases, Lab, Collections, Watchlist, and interactions.
- Keep API/interface boundaries clean: routers call application services, services call domain services/repositories, and API code does not reach into workflow executors.
- Record user behavior for future self-evolution.

**Non-Goals:**
- Full crawler expansion for every PRD data source.
- Production database migrations.
- Automatic code changes, automatic prompt rollout, or unreviewed evolution policy changes.
- Fake business project data when Project Radar output is absent.

## Decisions

- Add a `ProjectRadarBridge` that maps `BoardOutput`/card-shaped artifacts into Projects domain objects. It will accept both latest backend-like payloads and local artifact payloads.
- Use `.newsroom/projects/state.json` for mutable first-version state: watchlist items, lab sessions, interaction events, and evolution proposals. Business project entities remain derived from real Project Radar data.
- Keep deterministic ranking functions in `business/projects/ranking.py`; do not route score calculation through agents.
- Seed collections and cases only by deriving from real projects/capabilities. If no real projects exist, collection/case lists are empty with notices.
- For Lab v1, generate requirement profiles, graph nodes, questions, and solution drafts deterministically from the user problem plus available cases/projects.
- Frontend pages call a unified Projects API client and render empty states when backend data is unavailable.

## Risks / Trade-offs

- Existing Project Radar artifacts may contain incomplete repository metadata. DTO fields are optional where the PRD allows, and notices explain missing real data.
- Local JSON state is suitable for v1 and tests, but later production deployments should add a database-backed repository behind the same interface.
- Implementing all PRD routes in one change is broad; tests focus on data contracts, ranking behavior, critical API paths, and basic page rendering.
