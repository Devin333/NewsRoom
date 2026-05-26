## 1. OpenSpec

- [x] 1.1 Create proposal, design, specs, and tasks for `cross-board-evidence-graph-frontend-v1`.
- [x] 1.2 Validate `cross-board-evidence-graph-frontend-v1` with `openspec validate --strict`.

## 2. Types, Data, And API

- [x] 2.1 Add evidence graph TypeScript payload types.
- [x] 2.2 Add a graph data service that aggregates Papers, Projects, News, Community, and Reports from real loaders.
- [x] 2.3 Implement PRD-aligned graph matching, edges, scoring, timeline, related reports, and node detail lookup.
- [x] 2.4 Add BFF routes for `/api/evidence-graph`, `/api/evidence-graph/nodes/:id`, and `/api/topics/:topicId/timeline`.

## 3. UI

- [x] 3.1 Replace the current evidence graph route branch with the new feature page.
- [x] 3.2 Build the PRD-07 page layout: hero/search, summary, sidebar, evidence chain/timeline, inspector, evidence columns, related reports, and empty states.
- [x] 3.3 Update the homepage Evidence Graph module copy to the PRD wording.

## 4. Documentation And Tests

- [x] 4.1 Update PRD-07 status and implementation notes.
- [x] 4.2 Add unit tests for graph builder filtering, scoring, edge creation, timeline, and empty data.
- [x] 4.3 Add API route tests for graph, node detail, timeline, and missing node.
- [x] 4.4 Add component coverage for summary, evidence sections, inspector, timeline, and empty state.
- [x] 4.5 Update E2E navigation coverage for the Evidence Graph route and homepage entry.

## 5. Validation And Commit

- [x] 5.1 Run OpenSpec validation.
- [x] 5.2 Run frontend typecheck, test, build, and targeted E2E navigation spec.
- [x] 5.3 Commit the completed change as `feat(frontend): implement cross-board evidence graph`.
