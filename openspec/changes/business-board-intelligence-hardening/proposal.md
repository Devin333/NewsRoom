## Why

The business layer now has the PRD final-target structure, but the board and cross-board intelligence paths still behave like generic deterministic scaffolding. This change hardens the existing target-state modules so each board has visible business-specific scoring, presentation, and quality behavior while pipelines remain independently testable.

## What Changes

- Deepen AI News, Project Radar, Paper Radar, and Community Pulse ranking, presentation, policy, and workflow behavior without changing public DTO shapes.
- Decouple extraction, relation, and analysis pipelines so their named extractor/linker/analyzer modules own the core deterministic rules and pipelines orchestrate them.
- Strengthen cross-board journeys and insights with ordered evidence chains, multi-board support checks, confidence gates, and regression guard metadata.
- Connect board and cross-board quality failures to the existing feedback, learning-signal, policy-candidate, and manual guard flow.
- Preserve existing dependency boundaries and keep interfaces consuming board services and output DTOs.

## Capabilities

### New Capabilities

### Modified Capabilities
- `business-board-final-target-runtime`: board services must apply board-specific policy-aware ranking and presentation instead of generic pass-through ranking.
- `business-layer-final-target-pipelines`: named extractor/linker/analyzer modules must own independently testable deterministic rules while pipelines orchestrate them.
- `business-cross-board-intelligence`: cross-board intelligence must build ordered technology journeys and block unsupported insight chains with guard evidence.
- `business-foundation-quality-loop`: board and cross-board quality failures must feed feedback and policy candidate generation without automatic activation.
- `business-interface-board-contracts`: interface-facing board output must preserve no-raw-payload DTO contracts while exposing richer ranking, quality, and guard metadata.

## Impact

- Affected code: `business/boards/*`, `business/layers/{extraction,relation,analysis}`, `business/foundation/feedback`, and interface contract tests.
- Public contract impact: no breaking DTO changes; richer values are populated in existing fields.
- Dependencies: no new external dependencies, no real LLM calls, no automatic policy activation, no new business evolution or runner modules.
