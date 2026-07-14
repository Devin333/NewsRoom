## Design

The endpoint is read-only:

```text
GET /api/v1/runs/{run_id}/replay
  -> RunInspectionService.replay_run(run_id)
  -> ApiResponse(data=replay_bundle)
```

It reuses the service-level redaction, manifest parsing, event loading, and artifact read-error behavior added for the CLI. The API layer does not read artifact files directly.

## Validation

Tests cover successful replay, missing run error mapping, invalid replay request mapping, and a real filesystem-backed replay call through `TestClient`.
