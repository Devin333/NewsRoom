## Context

The output layer already has placeholder files for card/detail/insight/report builders, but those files re-export classes from `pipeline.py`. The pipeline currently owns DTO helper models, builder classes, and private helper functions in addition to orchestration.

## Goals / Non-Goals

**Goals:**
- Keep `BoardOutputPipeline` as the only orchestration object in `pipeline.py`.
- Give each output builder file one clear responsibility.
- Keep all existing board and interface callers working without signature changes.
- Add tests that lock the BoardCard, DetailPage, Report, and pipeline output contracts.

**Non-Goals:**
- No framework, storage, worker, API, or interface DTO changes.
- No board-specific ranking redesign.
- No new raw payload fields or new output-layer public schema fields.

## Decisions

- Reuse the existing output-layer files instead of adding a larger module tree. This keeps the change small and matches the current repository shape.
- Move `BoardOutput`, `BoardOutputStats`, and `BoardOutputSection` to `models.py`; keep `DetailBuildContext` with `detail_page_builder.py` because it is only used by the detail builder and pipeline orchestration.
- Preserve package exports in `business.layers.output.__init__` so existing imports from board services keep working.
- Keep builder behavior deterministic and equivalent to the existing pipeline logic; the change is structural hardening, not scoring redesign.

## Risks / Trade-offs

- Circular imports between builders and pipeline could break import compatibility → builders import models and foundation types directly, while pipeline imports builders.
- Moving helper functions could change serialization by accident → tests assert no `raw_payload` and required evidence/provenance/quality/ranking fields.
- OpenSpec has another completed business change active → this change remains scoped and independent; no archiving is required for implementation.
