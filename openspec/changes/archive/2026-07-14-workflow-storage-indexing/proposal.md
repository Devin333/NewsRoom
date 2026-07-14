## Why

The MVP must exercise real storage paths, not only isolated stores. Workflow runs currently write artifacts and events to the run directory, but the new storage-owned artifact index and event store are not populated by the runner assembly path.

## What Changes

- Wire `WorkflowRunner` to index manifest-declared artifacts after a run completes.
- Wire `WorkflowRunner` to append workflow event artifacts into `LocalJsonEventStore`.
- Preserve existing artifact files and manifest keys.
- Keep storage index files under the artifact root `_records` directory.

## Out Of Scope

- Replacing `ArtifactManager` writes with `FilesystemArtifactStore` writes.
- Changing `WorkflowExecutor` internals.
- PostgreSQL persistence for artifact/event metadata.
