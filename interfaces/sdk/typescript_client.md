# TypeScript SDK Contract

The TypeScript SDK should call the same `/api/v1` HTTP contract as `NewsClient`.

Minimum surface:

- `client.runs.createDaily({ topic, profile, sourceLimit })`
- `client.runs.get(runId)`
- `client.runs.list({ limit })`
- `client.runs.manifest(runId)`
- `client.runs.events(runId, { limit })`
- `client.runs.replay(runId)`
- `client.runs.diagnostics(runId)`
- `client.runs.health(runId)`
- `client.runs.catalogHealth()`
- `client.runs.compare({ baseRunId, targetRunId })`
- `client.reports.latest()`
- `client.reports.search({ query, limit })`
- `client.memory.search({ query, collection, filters, limit })`

SDK implementations must preserve the common `ApiResponse` / `ApiError` envelope and must not read runtime storage directly.
Run inspection helpers must call `/api/v1/runs/...` endpoints and must not read `.newsroom/runs` directly.
