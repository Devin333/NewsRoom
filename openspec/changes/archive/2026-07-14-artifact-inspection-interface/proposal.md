## Why

Run manifests index artifact files, but operators cannot list or inspect those redacted artifacts through a stable interface. The interface PRD calls out artifact list/show commands and APIs as first-phase read paths.

## What Changes

- Add artifact inspection application service backed by local run manifests.
- Add CLI `news artifacts list` and `news artifacts show`.
- Add API endpoints for run artifacts.
- Enforce run id and artifact path safety.

## Capabilities

### New Capabilities

- `artifact-inspection-interface`: Service, CLI, and API views for local run artifacts.

### Modified Capabilities

- `run-inspection-interface`: Run detail artifacts become navigable through a separate artifact service.

## Impact

- New service module and tests.
- Reads only artifacts referenced by manifest files under the artifact root.
- No local artifacts, OpenSpec files, or secrets are committed.
