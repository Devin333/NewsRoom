## Context

The frontend already has `/tech/repos`, `/projects`, `/projects/[slug]`, `/api/projects`, and `getProjectList`. Data loading first tries backend runs/artifacts for `project_radar-productized-board`, then local project artifacts, and returns an empty state when no real output exists. PRD-04 needs this surface to become a front-stage Project Radar Board rather than a generic project grid.

## Goals / Non-Goals

**Goals:**
- Make `/tech/repos` feel like the same reader-facing intelligence product as `/papers` and `/news`.
- Use real backend/artifact Project Radar data when available.
- Show clear empty/degraded states when real data is missing or incomplete.
- Preserve existing route and API compatibility.
- Provide both an in-page detail drawer and the existing shareable detail page.
- Fix visible mojibake in Project Radar UI.

**Non-Goals:**
- Adding GitHub OAuth, repository write actions, issue management, or backend collector monitoring.
- Adding a new backend endpoint or persistence model.
- Fabricating projects, clusters, maturities, or relations that are not supported by data.
- Implementing complex graph visualization in this change.

## Decisions

- `/tech/repos` is the primary Project Radar route; `/projects` remains a compatibility alias for the same board.
- `/tech/repos?project=<slug>` opens a detail drawer; `/projects/[slug]` reuses the same detail content for shareable navigation.
- Project data remains backend/artifact driven. Empty runtime data renders notices instead of substituting mock projects.
- PRD query aliases map into existing fields:
  - `topic` filters normalized categories and tags.
  - `period=daily|weekly|monthly|all` filters by real first-seen, created, updated, or pushed timestamps.
  - `maturity` filters derived maturity when enough real signals exist.
  - `sort=activity` maps to activity-oriented scoring; existing `growth` and `quality` remain compatible aliases.
  - `limit` maps to page size; `cursor` is accepted as a page-compatible alias when numeric.
- Maturity is derived only from real fields. If data is insufficient, the item shows a maturity-unavailable state and is not forced into a PRD maturity bucket.
- Cluster previews render only when multiple real items share a category, topic, or relation group.

## Risks / Trade-offs

- More complete PRD filters can make local pages empty when project artifacts are absent; that is intentional to avoid fake business data.
- Existing artifacts may not contain every PRD field. The mapper will expose optional fields and relation counts when available, while keeping existing cards functional.
