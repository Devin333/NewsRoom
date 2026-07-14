## Context

Workflow runtime writes redacted artifacts and records relative paths in each run manifest. The first artifact interface can safely read only files listed in the manifest, avoiding direct arbitrary path access.

## Goals / Non-Goals

**Goals:**

- List artifact keys, paths, content type, and size for a run.
- Show a specific artifact by manifest key.
- Parse JSON artifacts into structured content; return text for markdown/jsonl/plain artifacts.
- Reject path traversal and unknown artifact keys.

**Non-Goals:**

- Artifact search, binary download streaming, checksum verification, object storage, and ACL are deferred.

## Decisions

- Artifact identity in this increment is `(run_id, artifact_key)` where artifact key is the manifest `artifacts` map key.
- Only manifest-listed relative paths are readable.
- API 404 is used for missing runs/artifacts; invalid IDs return 400.

## Risks / Trade-offs

- Local file reads are development-friendly but not sufficient for large production storage. The service boundary can later use ArtifactStore and ArtifactIndexStore.
