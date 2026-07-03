## 1. Channel Contract

- [x] 1.1 Add OpenSpec proposal, design, spec, and task artifacts.
- [x] 1.2 Add `RankedHit`, `RankedList`, and `RecallChannel` protocol under `retrieval/channels/base.py`.
- [x] 1.3 Export the channel contract from package init files.

## 2. Fusion Module

- [x] 2.1 Add `retrieval/fusion.py` with `fuse_ranked_hits` and current-shape `fuse_chunk_rankings` adapter.
- [x] 2.2 Delegate `paper_retriever._rrf_fuse_rankings` to the new fusion module without changing behavior.

## 3. Tests And Validation

- [x] 3.1 Add tests for ranked hit shape and deterministic RRF fusion.
- [x] 3.2 Run retrieval tests, compile checks, and `openspec validate refactor-retrieval-pipeline-channels --strict`.
