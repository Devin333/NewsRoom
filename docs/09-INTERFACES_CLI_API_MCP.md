# NewsRoom Interfaces: CLI, API, SDK, MCP

## Interface Boundary

Interface code is an inbound adapter layer. CLI, API, SDK, MCP, and Web-facing modules call `interfaces.services.*` application services and return interface DTOs or business board DTOs. They must not import workflow executors, concrete storage clients, or business internals for presentation data.

Board presentation surfaces consume board services and output DTOs. A request for board data returns `BoardOutput` or `BoardRunResult` shaped data, including trace refs, manifest refs, cards, detail pages, insights, reports, quality summaries, policy snapshots, and feedback candidates when available.

## CLI Command Map

- `news run daily` starts a daily intelligence workflow through `RunApplicationService`.
- `news run weekly` starts a weekly intelligence workflow through `RunApplicationService`.
- `news reports latest` reads report summaries through `ReportApplicationService`.
- `news boards list` and board detail commands read board DTOs through `BoardApplicationService`.
- `news mcp catalog` exposes MCP tool/resource/prompt metadata through `MCPApplicationService`.
- `news interface-smoke` is the acceptance smoke path for checking CLI, API service wiring, MCP catalog access, and standard response envelopes.

## API Endpoint Map

- `GET /health` returns API health in the standard envelope.
- `POST /api/v1/runs/daily` creates a daily run.
- `POST /api/v1/runs/weekly` creates a weekly run.
- `GET /api/v1/reports` lists reports.
- `GET /api/v1/reports/{report_id}` returns a report detail DTO.
- `GET /api/v1/boards` lists available board views.
- `GET /api/v1/boards/{board_type}` returns board output through the board application service.
- `POST /api/v1/mcp/tools/{tool_name}` invokes MCP tools through the MCP application service.

## SDK Usage

The Python SDK mirrors the HTTP contract. It sends the same request bodies as API clients, preserves `Request-ID` correlation, and raises typed API errors from the standard envelope rather than exposing raw transport exceptions to callers.

## MCP Surface

The MCP surface publishes catalog, capability manifest, tools, resources, and prompts. Dangerous or external-write tools advertise `side_effect_level` and `requires_confirmation`; clients should confirm operations such as `news.run.cancel` before invoking them.

## Auth And Rate Limit

HTTP requests may use `Authorization: Bearer <token>` plus `X-API-Client-ID`. API middleware maps tokens to roles, applies rate limits when configured, and returns contract-shaped errors for unauthenticated, unauthorized, or rate-limited requests.

## Response Envelope

All API responses use the shared envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "request_id": "request-id"
}
```

Errors keep the same envelope shape with `ok: false`, an error code, a message, details, and the same `Request-ID` value.

## Request-ID

Clients should send `X-Request-ID` for traceability. When omitted, the API creates one, returns it in the response header, and stores it in the response envelope as `request_id`.

## Current Limits

- Interfaces do not call real LLMs directly; workflow services decide runtime profile behavior.
- Interfaces do not bypass business services to read concrete postgres, qdrant, redis, or artifact storage for board presentation data.
- Web console code remains a consumer of API contracts, not a direct framework runtime client.
- MCP stdio and HTTP surfaces share the same application service contracts.
