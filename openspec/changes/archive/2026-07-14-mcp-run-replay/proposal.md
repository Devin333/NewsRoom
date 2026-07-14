## Why

Run replay is now available through CLI and HTTP API, but MCP clients cannot read the same replay bundle. The Interface PRD expects MCP resources/tools for run inspection, and replay is a natural extension of the existing run manifest/events/artifact MCP resources.

## What Changes

- Add `news.run.replay` MCP tool.
- Add `news://runs/{run_id}/replay` MCP resource.
- Route both through `RunInspectionService.replay_run`.
- Keep existing redaction and read-error behavior from the run replay service.

## Out Of Scope

- Re-executing or resuming workflows.
- Streaming replay artifacts.
- Multi-run replay diffing.
