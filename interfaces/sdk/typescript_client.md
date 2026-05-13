# TypeScript SDK Contract

The TypeScript SDK should call the same `/api/v1` HTTP contract as `NewsClient`.

Minimum surface:

- `client.runs.createDaily({ topic, profile, sourceLimit })`
- `client.runs.get(runId)`
- `client.reports.latest()`
- `client.reports.search({ query, limit })`
- `client.memory.search({ query, collection, filters, limit })`

SDK implementations must preserve the common `ApiResponse` / `ApiError` envelope and must not read runtime storage directly.
