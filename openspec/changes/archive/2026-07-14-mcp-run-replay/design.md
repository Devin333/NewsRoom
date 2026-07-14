## Design

The MCP layer remains service-first:

```text
tool news.run.replay
  -> RunInspectionService.replay_run(run_id)

resource news://runs/{run_id}/replay
  -> RunInspectionService.replay_run(run_id)
```

The MCP service does not read files directly. It returns the same redacted replay bundle exposed by CLI/API.

## Validation

Tests cover catalog registration, tool call behavior, resource parsing, and real local artifact replay through MCP service and stdio resource read.
