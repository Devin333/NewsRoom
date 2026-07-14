## Design

Filesystem artifacts are stored under a configured run root:

```text
{root}/{run_id}/{relative_path}
```

Callers may provide `relative_path`. If omitted, the store generates a stable layout:

```text
artifacts/{artifact_type}/{artifact_id}.{ext}
steps/{step_id}/artifacts/{artifact_id}.{ext}
```

The store returns an `ArtifactRef` containing the canonical fields from the Storage architecture: artifact id, run id, optional step id, type, path, content type, size, checksum, redaction flag, creation time, and metadata.

The local index store writes one JSON record per artifact:

```text
{index_root}/{run_id}/{artifact_id}.json
```

It is synchronous to match existing local JSON repositories. It sorts returned refs by `created_at` and then `artifact_id` for deterministic results.

## Validation

Tests cover model roundtrip, real filesystem write/read/exists/delete behavior, checksum mismatch detection, index by run and step, and unsafe path/id rejection. A smoke script writes and indexes a real local artifact file.
