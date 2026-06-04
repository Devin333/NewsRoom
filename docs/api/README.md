# NewsRoom HTTP API

The HTTP API is a FastAPI interface over application services. It validates requests, returns the standard envelope, maps errors, and exposes OpenAPI for SDK generation and contract checks.

## Start The API

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

Routes under `/api/` require auth only when token configuration is provided to `create_app`. Health endpoints remain unauthenticated.

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

Errors put `code`, `message`, `details`, `retryable`, `user_action_required`, and `request_id` under `error`.

## Current Endpoint Groups

```text
GET  /health
POST /api/v1/research/papers/analyze
GET  /api/v1/research/papers/{paper_id}/analysis
GET  /api/v1/research/papers/{paper_id}/reader
POST /api/v1/research/papers/{paper_id}/ask
GET  /api/v1/research/runs/{run_id}/trace
GET  /api/v1/runs
GET  /api/v1/runs/{run_id}/events
GET  /api/v1/runs/{run_id}/replay
GET  /api/v1/reports/latest
GET  /api/v1/reports
POST /api/v1/memory/search
GET  /api/v1/sources/health
GET  /api/v1/workers
GET  /api/v1/mcp/catalog
GET  /api/v1/mcp/manifest
```

Use `docs/api/openapi.json` as the generated endpoint contract. Legacy board and paper API paths are intentionally absent.
