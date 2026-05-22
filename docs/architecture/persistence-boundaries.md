# Persistence Boundaries

NewsRoom separates runtime artifacts from operational persistence.

## Artifact Store

Framework artifacts and manifests describe runtime evidence such as reports, events, step outputs, checkpoints, gate results, and inspection data. Artifact store protocols belong in `framework/artifacts`; concrete stores live in infrastructure.

## Persistence Repository

`infrastructure/storage/persistence` contains persistence repository contracts, record models, and adapters:

- `repository.py`: `PersistenceRepository`, factory functions, and run-result conversion helpers.
- `records.py`: `WorkflowRunRecord`, `ReportRecord`, and `RunPersistenceBatch`.
- `local_json_adapter.py`: local JSON persistence adapter.
- `postgres_adapter.py`: PostgreSQL adapter export when configured.

The old `infrastructure.storage.repository` path remains as a compatibility export.

## Business Records

Business report, evidence, claim, quality, and source records remain business concepts. Persistence adapters serialize them without changing business semantics.

## Storage Types

Local JSON is the offline fallback and keeps the existing path/data format. PostgreSQL is the relational persistence adapter. Vector storage is for memory recall and indexing. Checkpoint storage is for workflow resumption and is not the same thing as run/report persistence.
