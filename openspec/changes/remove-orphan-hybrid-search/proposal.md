## Why

PRD 16 explicitly lists `infrastructure/storage/hybrid_search.py` as an orphan compatibility module to delete. Current code confirms it has no production callers; only its own tests import it. Keeping it conflicts with the real Paper RAG retrieval pipeline, which now owns sparse/dense/field/claim/visual recall and RRF-style fusion. The active storage spec still describes the old storage-layer hybrid search, so the spec must be updated together with the deletion.

## What Changes

- Delete `infrastructure/storage/hybrid_search.py`.
- Delete its orphan unit test.
- Update the active storage spec to remove the obsolete storage-layer hybrid search requirement.
- Add a spec note that Paper RAG hybrid retrieval is owned by `business.research.rag.retrieval`, not storage.

## Capabilities

### Removed Capabilities

- `storage-memory-final-target-closure`: Storage no longer exposes the orphan report/vector hybrid search service.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `infrastructure/storage/hybrid_search.py`
  - `tests/infrastructure/storage/test_hybrid_search.py`
  - `openspec/specs/storage-memory-final-target-closure/spec.md`
- No production callers are expected to break because the deleted module has no non-test references.
