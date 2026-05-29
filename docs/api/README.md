# NewsRoom HTTP API

The HTTP API is a FastAPI interface over application services. It validates
requests, returns the standard envelope, maps errors, and exposes OpenAPI for
SDK generation and contract checks.

## Start The API

```bash
news api serve --host 127.0.0.1 --port 8000
```

or:

```bash
python -m interfaces.cli.news api serve --host 127.0.0.1 --port 8000
```

The app factory is `interfaces.api.create_app`.

## OpenAPI

Export the current schema:

```bash
python -m scripts.dev export-openapi
```

The generated file is `docs/api/openapi.json`. Contract checks are:

```bash
python -m scripts.dev test-api-contracts
python -m pytest tests/interfaces/api/test_openapi_contract.py -q
```

## Authentication

When the API is configured with tokens, send:

```text
Authorization: Bearer <token>
X-API-Client-ID: <client id>
X-Request-ID: <trace id>
```

Routes under `/api/` require auth only when token configuration is provided to
`create_app`. Health endpoints remain unauthenticated.

## Envelope

Every JSON response uses:

```json
{
  "success": true,
  "data": {},
  "error": null,
  "request_id": "req_...",
  "schema_version": "1.0"
}
```

Errors put `code`, `message`, `details`, `retryable`,
`user_action_required`, and `request_id` under `error`.

## Common Error Codes

```text
invalid_request
unauthorized
forbidden
not_found
workflow_not_found
report_not_found
run_not_found
rate_limited
internal_error
```

Endpoint-specific codes may refine these, for example
`invalid_run_operation_request` or `artifact_not_found`.

## Useful Endpoint Groups

```text
GET  /health
POST /api/v1/runs
GET  /api/v1/runs/{run_id}/events
GET  /api/v1/reports/latest
GET  /api/v1/projects
GET  /api/v1/projects/hot
GET  /api/v1/projects/rising
GET  /api/v1/projects/tools
GET  /api/v1/projects/cases
GET  /api/v1/projects/collections
GET  /api/v1/projects/watchlist
POST /api/v1/memory/search
GET  /api/v1/sources/health
GET  /api/v1/workers
GET  /api/v1/mcp/catalog
GET  /api/v1/mcp/manifest
```

Use `docs/api/openapi.json` as the generated endpoint contract.

## Projects

Projects is the productized Project Radar module. The backend reads real
Project Radar artifacts from Project Radar-marked run directories, manifests, or
artifact payloads under `.newsroom/runs`, and does not substitute fake runtime
projects when no artifact exists. Mutable Lab, Watchlist, and interaction state
is stored under `.newsroom/projects/state.json` by default.

```text
GET    /api/v1/projects
GET    /api/v1/projects/hot
GET    /api/v1/projects/rising
GET    /api/v1/projects/{project_id}
GET    /api/v1/projects/tools
GET    /api/v1/projects/tools/{project_id}
POST   /api/v1/projects/tools/compare
POST   /api/v1/projects/tools/recommend
GET    /api/v1/projects/cases
GET    /api/v1/projects/cases/{case_id}
POST   /api/v1/projects/lab/sessions
POST   /api/v1/projects/lab/sessions/{session_id}/answer
POST   /api/v1/projects/lab/sessions/{session_id}/generate-solution
GET    /api/v1/projects/collections
GET    /api/v1/projects/collections/{slug}
GET    /api/v1/projects/watchlist
POST   /api/v1/projects/watchlist
PATCH  /api/v1/projects/watchlist/{item_id}
DELETE /api/v1/projects/watchlist/{item_id}
POST   /api/v1/projects/interactions
```
