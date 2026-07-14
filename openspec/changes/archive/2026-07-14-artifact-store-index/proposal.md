## Why

The Storage / Memory target architecture defines `ArtifactRef`, `ArtifactStore`, and `ArtifactIndexStore` as canonical storage contracts. The current runtime can write run files, but there is no storage-owned artifact reference model or index store that other modules can depend on for replay, audit, and future PostgreSQL metadata.

## What Changes

- Add a serializable `ArtifactRef` model and `ArtifactWriteRequest`.
- Add a filesystem artifact store that writes real artifact bytes under a run directory, computes size and checksum, and reads/deletes by reference.
- Add a local JSON artifact index store that persists `ArtifactRef` records and lists them by run or step.
- Reject unsafe ids and relative paths.

## Out Of Scope

- Migrating existing workflow artifact writes to the new store.
- PostgreSQL artifact metadata repository.
- Remote object storage and retention jobs.
