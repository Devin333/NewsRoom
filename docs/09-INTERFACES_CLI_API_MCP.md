# NewsRoom Interfaces: CLI, API, SDK, MCP

## Interface Boundary

Interface code is an inbound adapter layer. CLI, API, SDK, MCP, webhook, and web-facing modules call `interfaces.services.*` application services and return interface DTOs. They must not import workflow executors, concrete storage clients, or business internals for presentation data.

The current backend product surface is Harness + Research. Legacy board, paper ingest, daily run, weekly run, and old paper reader routes are retired from the registered interface surface.

## CLI Command Map

- `news api serve` starts the HTTP API server.
- `news api openapi` exports the current OpenAPI schema.
- `news runs list`, `news runs show`, `news runs events`, and `news runs replay` inspect Harness run artifacts.
- `news reports list`, `news reports show`, and `news latest` read persisted reports through `ReportApplicationService`.
- `news schedules` manages generic task schedules such as source health checks and memory reindex tasks.
- `news workers` and `news worker` inspect workers and queues.
- `news sources` lists, probes, validates, and fetches configured real sources.
- `news memory` searches and reindexes memory.
- `news mcp catalog` exposes MCP tool, resource, and prompt metadata through `MCPApplicationService`.

## API Endpoint Map

- `GET /health`, `/health/live`, `/health/ready`, and `/health/dependencies` return API health in the standard envelope.
- `POST /api/v1/research/papers/analyze` starts a Research paper analysis request.
- `GET /api/v1/research/papers/{paper_id}/analysis` returns the stored Research analysis payload.
- `GET /api/v1/research/papers/{paper_id}/reader` returns the Research reader payload.
- `POST /api/v1/research/papers/{paper_id}/ask` answers a paper question with evidence refs.
- `GET /api/v1/research/runs/{run_id}/trace` returns the Harness trace for a Research run.
- `GET /api/v1/runs*` inspects run manifests, events, replay bundles, health, diagnostics, artifacts, and operations.
- `GET /api/v1/reports*` lists and reads persisted reports.
- `GET /api/v1/sources*` and `POST /api/v1/sources/*` expose configured source operations.
- `GET /api/v1/mcp/catalog` and related MCP routes expose the MCP surface.

Retired routes such as `/api/v1/papers*`, `/api/v1/boards*`, `/api/v1/runs/daily`, and `/api/v1/runs/weekly` must remain unregistered.

## SDK Usage

The Python SDK mirrors the HTTP contract. It sends the same request bodies as API clients, preserves request correlation, and raises typed API errors from the standard envelope rather than exposing raw transport exceptions to callers. Research API examples live in `examples/api/analyze_research_paper.py` and `examples/sdk/analyze_research_paper.py`.

## MCP Surface

The MCP surface publishes catalog, capability manifest, tools, resources, and prompts. Dangerous or external-write tools advertise `side_effect_level` and `requires_confirmation`; clients should confirm operations such as `news.run.cancel` before invoking them.

## Auth And Rate Limit

HTTP requests may use `Authorization: Bearer <token>` plus `X-API-Client-ID`. API middleware maps tokens to roles, applies rate limits when configured, and returns contract-shaped errors for unauthenticated, unauthorized, or rate-limited requests.

## Response Envelope

All API responses use the shared envelope:

```json
{
  "success": true,
  "data": {},
  "error": null,
  "request_id": "request-id",
  "schema_version": "1.0"
}
```

Errors keep the same envelope shape with `success: false`, an error code, a message, details, and the same request id.

## Request-ID

Clients should send `X-Request-ID` for traceability. When omitted, the API creates one, returns it in the response header, and stores it in the response envelope as `request_id`.

## Current Limits

- Interfaces do not call real LLMs directly; Harness and application services own runtime profile behavior.
- Interfaces do not bypass application services to read concrete postgres, qdrant, redis, or artifact storage.
- Web console code remains a consumer of API contracts, not a direct framework runtime client.
- MCP stdio and HTTP surfaces share the same application service contracts.
- `python -m scripts.dev interface-smoke` remains the interface-layer acceptance command.
