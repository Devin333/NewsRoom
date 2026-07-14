## Design

`register_artifact_tools(registry, artifact_manager, run_id)` registers:

```text
artifact.write
artifact.load
```

`artifact.write` is marked as local-state side-effecting, so default ToolPolicy
approval behavior still applies unless a caller explicitly disables the local
side-effect approval gate for trusted runtime paths.

`artifact.load` is read-only and concurrency-safe. Both tools reject absolute
paths and path traversal by resolving paths under `ArtifactManager.run_dir`.

## Validation

Focused tests use a real temporary artifact root, write a JSON artifact through
ToolExecutor, load it back through ToolExecutor, and verify traversal rejection.
