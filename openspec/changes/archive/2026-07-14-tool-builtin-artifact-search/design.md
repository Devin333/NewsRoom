## Design

`artifact.search` walks the current run directory from `ArtifactManager.run_dir`.
It rejects absolute or parent-traversal prefixes. Results include:

- `artifact_id`
- `relative_path`
- `content_type`
- `size_bytes`
- `matched_on`

When `query` is provided, the tool matches case-insensitively against relative
paths and a bounded text preview for text/JSON artifacts. Full content is never
returned by search; callers can use `artifact.load` for specific artifacts.

## Compatibility

Existing `artifact.write` and `artifact.load` behavior is unchanged.
