## Durable Run Event Interface Evidence

Tasks: `8.2`, `8.3`

The online run-event surface now reads the application-owned durable reader first. It preserves legacy filters, `limit`, and `offset`, adds checksum-protected finite snapshot cursors, and exposes the same metadata through HTTP, CLI, MCP tools/resources, and the Python SDK.

SSE uses a separate checksum-protected `newsroom.run-event-sse-cursor/v1` because a finite snapshot cursor cannot represent a consumer waiting at the current stream tail. HTTP reads `Last-Event-ID`, rejects simultaneous snapshot and SSE cursors, emits the opaque cursor only for authoritative durable events, and emits no durable event id for projection fallback rows.

Both event and progress SSE endpoints consume the opaque resume cursor. A nonzero cursor is rejected when the authorized durable stream is empty, and the default query/SSE page size is 100 with a hard maximum of 1,000.

Store failure is explicit:

- an existing projection may be returned only with `availability=unavailable`, `source=projection`, and `projection_status=stale`;
- an absent projection returns an empty `projection_status=unavailable` result instead of a false 404;
- disabling stale fallback produces a retryable HTTP 503 and CLI exit code 2;
- SSE done metadata includes projection checksum/watermark and unavailable reason.

Before any stale projection rows are returned, the application service performs one bounded streaming pass that validates the manifest checksum, event count, high watermark, stream/tenant scope, sequence continuity, and each row's projection checksum. Missing, appended, truncated, oversized, or otherwise corrupt files return an empty typed unavailable result. Durable storage composition is lazy, so artifact-only run inspection does not initialize or write an event database.

MCP resource reads accept query continuation, for example `news://runs/run-1/events?sequence_cursor=...&limit=100`. OpenAPI now references `RunEventsApiResponse` and `RunEventsData` for the run-event endpoint, including source, availability, cursor, watermark, and projection fields.

Verification on 2026-07-16 against the isolated staged snapshot:

```text
focused service/transport/OpenAPI/SDK/MCP/architecture: 118 passed
required smoke gate: 1008 passed, 23 skipped
source validation: is_valid=true, error_count=0, warning_count=0
compile: passed
```

The broader durable read cutover for replay, diagnostics, health, comparison, and timeline remains tracked by task `9.3`.
