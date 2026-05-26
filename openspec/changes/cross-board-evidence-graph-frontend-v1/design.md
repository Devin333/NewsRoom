## Context

The Portal already has real loaders for News, Projects, Papers, Community, and Reports. `/topics?view=evidence-graph` currently reuses homepage module summaries, which proves the route is reachable but does not satisfy PRD-07's topic evidence graph behavior.

## Decisions

- Put graph-specific implementation under `frontend/src/features/evidence-graph` and shared payload types under `frontend/src/types/evidence-graph.ts`.
- Use existing real data loaders only: `getNewsListResult`, `getProjectList`, `getPublishedPaperData`, `getCommunityList`, and the existing safe Reports API read pattern.
- Build a deterministic graph in the BFF layer from public runtime data. The topic node is the root; paper, project, news, community signal, and report records become evidence nodes.
- Match records by normalized topic text, tags, entity names, related references, titles, summaries, and GitHub/arXiv URLs. Create only explainable edges; uncertain matches remain as standalone nodes.
- Implement PRD scoring as deterministic functions over the assembled graph:
  - Evidence score from source diversity, node count, average confidence, recency, and cross-board coverage.
  - Trend score from per-board velocity and report mentions.
  - Confidence score from verified source ratio, cross-source agreement, source reliability, and contradiction penalty.
- Keep the MVP visual structure layout-first rather than force-directed: summary, signal mix, evidence columns, timeline, and inspector.

## Data Shape

- `GET /api/evidence-graph` returns `{ summary, nodes, edges, timeline, relatedReports }`.
- `GET /api/evidence-graph/nodes/:id` returns `{ node, incomingEdges, outgoingEdges, relatedNodes }`.
- `GET /api/topics/:topicId/timeline` returns `{ items }`.
- All three routes use the local Next envelope `{ success, data, error }` used by adjacent BFF routes.

## Risks

- Source loaders can be partially empty or degraded. The graph service must return explicit notices and empty sections without throwing.
- Existing Paper Radar and Community Pulse work is active in the worktree. Edits should avoid unrelated files and preserve current changes.
- Because there is no persistent topic graph database yet, v1 matching is deterministic and explainable but not exhaustive.
