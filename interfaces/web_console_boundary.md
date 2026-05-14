# Web Console API Boundary

Version: newsroom.web_console_boundary.v1
Module: Interfaces / Web Console Boundary

The Web Console is an HTTP API consumer. It must not import storage, workflow,
worker, source, quality, or runtime modules directly, and it must not read or
write the database or artifact filesystem outside the HTTP API.

All page workflows use `/api/v1/*` endpoints and receive the shared
`ApiResponse` / `ApiError` envelope with `request_id` and `schema_version`.

## Cross-Cutting Contract

- Auth and RBAC are enforced by the HTTP API middleware.
- Write operations emit audit events and use redacted payload metadata.
- Long-running work is represented by task/run status and artifact refs.
- Large artifacts are linked by endpoint or artifact ref, not embedded in page
  lists.
- Real-time views use polling first, with `/progress` or `/events/stream` as the
  SSE boundary when enabled.

## Runs Page

Required views:

- list runs
- detail
- manifest
- events
- artifacts
- replay
- progress

HTTP API:

- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/manifest`
- `GET /api/v1/runs/{run_id}/events`
- `GET /api/v1/runs/{run_id}/events/stream`
- `GET /api/v1/runs/{run_id}/progress`
- `GET /api/v1/runs/{run_id}/artifacts`
- `GET /api/v1/runs/{run_id}/replay`
- `GET /api/v1/runs/{run_id}/diagnostics`
- `GET /api/v1/runs/{run_id}/health`
- `GET /api/v1/runs/compare`

## Reports Page

Required views:

- latest report
- list and search
- detail
- markdown
- quality
- publish
- request review

HTTP API:

- `GET /api/v1/reports/latest`
- `GET /api/v1/reports`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/reports/{report_id}/markdown`
- `GET /api/v1/reports/{report_id}/quality`
- `POST /api/v1/reports/{report_id}/publish`
- `POST /api/v1/reports/{report_id}/request-review`
- `GET /api/v1/search/reports`

## Sources Page

Required views:

- source list
- health
- validation
- probe

HTTP API:

- `GET /api/v1/sources`
- `GET /api/v1/sources/health`
- `GET /api/v1/sources/validation`
- `GET /api/v1/sources/{source_id}`
- `POST /api/v1/sources/{source_id}/probe`

## Workers Page

Required views:

- workers
- queues
- schedules
- manual schedule trigger

HTTP API:

- `GET /api/v1/workers`
- `GET /api/v1/workers/{worker_id}`
- `GET /api/v1/queues`
- `GET /api/v1/schedules`
- `POST /api/v1/schedules/daily`
- `POST /api/v1/schedules/tick`
- `POST /api/v1/schedules/{schedule_id}/trigger`

## Approvals Page

Required views:

- list
- show
- approve
- reject
- modify
- resume context

HTTP API:

- `GET /api/v1/approvals`
- `POST /api/v1/approvals`
- `GET /api/v1/approvals/{approval_id}`
- `POST /api/v1/approvals/{approval_id}/approve`
- `POST /api/v1/approvals/{approval_id}/reject`
- `POST /api/v1/approvals/{approval_id}/modify`
- `POST /api/v1/approvals/{approval_id}/resume-context`
- `POST /api/v1/approvals/{approval_id}/resume-workflow`

## Memory Page

Required views:

- search
- document
- reindex

HTTP API:

- `POST /api/v1/memory/search`
- `GET /api/v1/memory/{document_id}`
- `POST /api/v1/memory/reindex`

## Storage And Artifacts Boundary

The Web Console reads artifacts only through HTTP API resource endpoints. It
does not resolve local paths directly.

HTTP API:

- `GET /api/v1/artifacts`
- `GET /api/v1/artifacts/{artifact_id}`
- `GET /api/v1/storage/metrics`
- `GET /api/v1/storage/retention/plan`

## Health Boundary

HTTP API:

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /health/dependencies`
