## Context

`RetrievalPipeline.retrieve()` now orchestrates the retrieval stages, but it still contains a long metadata dictionary plus helper functions for field hit summaries and score extremes. This makes the pipeline longer than the PRD 16 target and mixes observability assembly with stage flow.

## Goals / Non-Goals

**Goals:**

- Extract metrics assembly into a dedicated module.
- Keep every existing metadata key and value semantics intact.
- Make the metrics builder independently testable.
- Reduce `pipeline.py` toward the PRD 16 size target without changing retrieval behavior.

**Non-Goals:**

- Do not introduce new metadata fields except through existing inputs.
- Do not change `RetrievalTrace` schema.
- Do not move policy YAML loading or parser cascade logic.

## Decisions

- **Builder takes explicit keyword inputs:** The pipeline will pass all stage outputs explicitly instead of the builder reading pipeline internals. This keeps dependencies visible and testable.
- **Builder owns helper functions:** `_field_hits_by_name`, `_metadata_extreme`, and `_best_matching_fields` belong with metrics assembly and move with it.
- **Policy hash remains computed in pipeline:** The trace is created before recall so sparse degradation recording can happen during recall. The builder receives the hash and trace after stages complete.

## Risks / Trade-offs

- **Many builder parameters** -> This mirrors the current metadata contract and is preferable to hiding state in a mutable context object for this narrow refactor.
- **Metrics still large** -> The field set is intentionally unchanged. Later work can group or version metrics after parity is stable.
