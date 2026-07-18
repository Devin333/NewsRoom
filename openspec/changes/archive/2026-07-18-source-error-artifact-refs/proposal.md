## Why

`05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md` defines `SourceError.request_ref`
and `SourceError.response_ref`, but failed source artifacts currently do not
link back to the fetch request/result artifacts that explain the failure.

## What Changes

- Persist per-error links to the matching `source_fetch_request` and
  `source_fetch_result` artifact refs when those records exist.
- Carry the source fetch `request_id` on source errors emitted by the daily
  source collection step so run-level diagnostics can be joined without path
  guessing.
- Expose the same request/result refs on `source_artifacts/index.json` entries
  and inside the persisted source error artifact payload.
- Keep all OpenSpec files, local artifacts, generated outputs, and secrets out
  of commits.

## Capabilities

### New Capabilities
- `source-error-artifact-refs`: Source error artifacts can be traced to the
  request/result artifact refs for the fetch attempt that produced the error.

### Modified Capabilities

## Impact

- `core/framework/artifacts/source_artifacts.py`
- `workflows/daily_intelligence/runner.py`
- Source artifact writer and daily workflow tests
