# NewsRoom Web Console

The Web Console is the browser-facing interface for NewsRoom operators. It
consumes the same API contracts documented in `docs/09-INTERFACES_CLI_API_MCP.md`
and must not import workflow runtime, concrete storage clients, or business
internals directly.

## Local Development

```bash
cd apps/web
npm install
npm run dev
```

Point the console at a backend with:

```bash
set NEWSROOM_API_BASE_URL=http://localhost:8000
```

## Operator Surface

The console is expected to remain a thin client over interface services:

- Runs: list runs, inspect manifests, events, diagnostics, artifacts, replay
  payloads, and operation status.
- Reports: list and read persisted reports.
- Sources: inspect configured sources, health, reliability, and fetch previews.
- Workers and queues: read status for local and Redis-backed execution.
- Memory: trigger interface-backed search and reindex operations.
- Approvals: submit review decisions through API contracts.
- Settings: show configured API and environment state.

## Safety Expectations

Write operations must use explicit API endpoints and surface the same
confirmation requirements as CLI and MCP tools. Destructive or external-write
operations need a visible reason, actor context, and confirmation before the UI
submits the request.

The console should display API `request_id` values when an operation fails so
operators can correlate browser actions with API logs and Harness transcripts.

## Local Checks

Use the interface and web checks before shipping console-facing changes:

```bash
python -m scripts.dev interface-smoke
python -m scripts.dev web-check
```
