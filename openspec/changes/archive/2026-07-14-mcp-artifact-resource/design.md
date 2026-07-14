## Design

The existing `ArtifactInspectionService` already validates run manifests, artifact keys, relative paths, content type, and file existence. MCP should delegate to that service instead of reading files directly.

Use the resource URI:

```text
news://runs/{run_id}/artifacts/{artifact_key}
```

This mirrors the existing HTTP API shape and avoids inventing a global artifact id before the storage layer defines one. The resource catalog exposes the template, and `read_resource` parses run id plus artifact key before delegating.

## Validation

Tests should create a real temporary run directory with `manifest.json` and artifact files, then read the MCP resource through `MCPApplicationService`.

Smoke should read an existing `.newsroom/runs/<run_id>` artifact through the CLI MCP adapter.

Structured JSON and JSONL artifact content is redacted inside `ArtifactInspectionService`, so CLI, API, and MCP all share the same safe content path.
