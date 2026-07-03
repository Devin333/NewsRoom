## Why

The web console can inspect workflow runs, but it does not yet provide the Studio Agent Run observability surface described by the frontend Task 04 PRD. Operators need a focused Studio view that answers what an agent run did, where it failed, which tools and memories were involved, and which artifacts and quality checks resulted from the run.

## What Changes

- Add `/studio`, `/studio/runs`, and `/studio/runs/[runId]` to `frontend`.
- Add a Studio overview, dense agent run list, and interactive run detail with DAG, step detail, logs, tool calls, memory hits, artifacts, quality, and errors.
- Use existing `/api/v1/runs*` HTTP API data first and merge high-quality mock observability data for fields not yet exposed by the backend.
- Add minimal frontend dependencies for `@xyflow/react` and `zustand`.
- Preserve existing `/runs` pages and the current web console shell.

## Capabilities

### New Capabilities

- `frontend-studio-agent-run-observability`: Studio pages can inspect agent run history and detail observability evidence.

### Modified Capabilities

- None.

## Impact

- Affected code: `frontend/src/app/studio`, `frontend/src/features/studio`, `frontend/src/stores`, `frontend/src/types/agent.ts`, `frontend/src/components/layout/sidebar.tsx`, and root layout CSS imports.
- Dependencies: reuse existing `reactflow` and `zustand` dependencies from `frontend/package.json`.
- API boundary: frontend remains an HTTP API consumer and does not import runtime, storage, or artifact filesystem modules directly.
