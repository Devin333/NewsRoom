## Why

The Interface PRD includes run replay API capability. The replay service and CLI now exist, but HTTP clients and future Web Console code still cannot request the same replay bundle through the API.

## What Changes

- Add `GET /api/v1/runs/{run_id}/replay`.
- Route the endpoint through `RunInspectionService.replay_run`.
- Return the standard `ApiResponse` envelope.
- Map missing runs to `run_not_found` and invalid run ids or replay paths to `invalid_run_replay_request`.

## Out Of Scope

- Async replay jobs.
- Replay execution or resume.
- Streaming large replay artifacts.
- Auth/authz.
