## Context

The current frontend contains both Portal and Studio routes. `/papers` uses the desired research/editorial visual system, but `/` still imports the legacy dashboard home and can render Studio shell content depending on the frontend surface mode. Portal navigation is mostly user-facing, but Papers still includes older mixed links and Community Pulse is not treated as a first-class Portal path.

## Goals / Non-Goals

**Goals:**
- Make Portal `/` a public reader-facing homepage.
- Keep Admin `/` and `/studio/**` protected and Studio-oriented.
- Reuse existing real data loaders for homepage summaries instead of hardcoded business facts.
- Keep `/papers` behavior stable while reusing its visual language.
- Remove dashboard-only homepage code after the new homepage owns `/`.

**Non-Goals:**
- Rewriting the existing News, Projects, Papers, Community, or Reports pages.
- Adding new backend APIs or persistence.
- Making every Portal content route public.
- Migrating Studio functionality into the Portal homepage.

## Decisions

- Keep the root route server-rendered and branch only for Admin mode. Portal mode renders the new homepage directly; Admin mode continues to render Studio dashboard content at `/` behind middleware auth.
- Put homepage-specific code under `frontend/src/features/portal` so it does not couple to papers internals beyond shared presentation primitives and existing data loaders.
- Load homepage summaries through existing server-side data functions: `getNewsListResult`, `getProjectList`, `getPublishedPapers`, and `getCommunityList`. Failures produce module-level degraded metadata rather than blocking the entire homepage.
- Use `/community` as the Community Pulse entry and add it to Portal route handling.
- Implement the Evidence Graph route as a structured Topic view inside the existing `/topics` surface when `view=evidence-graph` is present.
- Remove the legacy dashboard feature/lib/API/type tree only after search confirms no non-dashboard code depends on it.

## Risks / Trade-offs

- Homepage aggregation can be slower than a static page because it touches several data loaders -> cap list sizes and tolerate per-module failures.
- Existing tests expecting Portal login default `/papers` must be updated -> cover the new `/` default and public root behavior.
- Deleting dashboard code may expose hidden references -> use `rg` and typecheck/build as the source of truth before committing.
