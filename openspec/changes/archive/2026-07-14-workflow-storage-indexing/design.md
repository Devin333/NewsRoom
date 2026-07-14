## Design

`WorkflowRunner` is the assembly layer for local workflow execution. After `WorkflowExecutor.execute()` returns, the runner indexes the produced artifacts and events:

```text
{artifact_root}/_records/artifact_index/{run_id}/{artifact_id}.json
{artifact_root}/_records/events/{run_id}.jsonl
```

Artifact indexing reads the final manifest's `artifacts` map, verifies the referenced files exist, computes byte size and SHA-256 checksum, and writes `ArtifactRef` records. The artifact id is derived from the manifest artifact key and the original key is preserved in metadata.

Event indexing reads the existing `events.jsonl` artifact and converts each line to the storage-owned `EventRecord`. Step ids are lifted from payloads when present so `list_by_step()` works on workflow events.

## Validation

Tests run a real local workflow and assert that `_records/artifact_index` and `_records/events` are populated from the actual generated artifacts/events. A smoke command runs the daily workflow in `live-offline` mode and reads the storage index/event store back.
