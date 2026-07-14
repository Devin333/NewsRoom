## Design

Replay is read-only. It loads:

```text
{artifact_root}/{run_id}/manifest.json
{artifact_root}/{run_id}/{events artifact}
{artifact_root}/{run_id}/{each manifest artifact path}
```

The service reuses the existing sensitive-key redaction behavior for events and applies the same redaction to JSON and JSONL artifacts. Text and Markdown artifacts are returned as text. Missing or unreadable artifacts are represented with `read_error` on the artifact entry so the replay bundle remains useful for debugging partial runs.

CLI shape:

```text
news runs replay daily-offline --artifact-root .newsroom/runs --json
news runs replay daily-offline
```

The CLI remains a thin adapter over `RunInspectionService`.

## Validation

Tests cover replay from real manifest, events, JSON, JSONL, and Markdown artifacts. CLI tests use real files rather than fake service payloads. A real CLI smoke creates a minimal run directory and replays it through the command.
