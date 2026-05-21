## Why

`business/layers/output/pipeline.py` still mixes DTO models, builders, helper rules, and orchestration. This makes the output layer harder to test independently and risks turning the pipeline back into a business-detail dumping ground.

## What Changes

- Move output DTO helper models and builder implementations into dedicated output-layer modules.
- Keep `BoardOutputPipeline.build_board_output(...)` as the stable orchestration entrypoint.
- Add output-layer hardening tests for no-raw BoardCard serialization, evidence/provenance/quality/ranking contract, detail/report sections, and split builder execution.
- Preserve existing board services, cross-board service, interfaces, storage, and framework behavior.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `business-layer-final-target-pipelines`: Clarify that the output pipeline keeps output DTO contracts while delegating card, detail, insight, report, section, and quality logic to focused output-layer helpers.

## Impact

- Affected code: `business/layers/output/*` and business-layer tests.
- Public API impact: none; package-level output imports remain compatible.
- Dependency impact: none; no new external dependencies.
