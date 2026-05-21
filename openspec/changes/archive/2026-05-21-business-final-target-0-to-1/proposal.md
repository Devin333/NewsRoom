## Why

The business PRD package defines NewsRoom as an AI technology-evolution intelligence system, but the current business layer only has partial foundation, pipeline, board, and interface coverage. This change brings the business runtime to the documented 0-1 final target so evidence, provenance, quality, feedback, policy snapshots, and regression guards are native contracts instead of later add-ons.

## What Changes

- Add final-target business foundation contracts for quality, feedback, policy profiles, learning signals, policy candidates, and regression guard results.
- Extend layer pipelines so Signal, Extraction, Relation, Analysis, and Output expose standardized result models, rejection/warning metadata, evidence, stats, and explainable score features.
- Complete the four board vertical slices with policy-aware ranking, presenters, workflows, BoardRunResult outputs, quality summaries, feedback candidates, and required module layout.
- Add cross-board relation views, technology journeys, technology radar output, insight generation, policy profiles, and blocking/regression guard behavior.
- Add interface contracts so CLI/API/MCP/Web-facing code consumes board services and DTOs without reaching into concrete storage.
- Preserve existing runtime paths and legacy daily-intelligence code as reference/compatibility code, while target-state business code follows `foundation -> layers -> boards -> interfaces`.

## Capabilities

### New Capabilities
- `business-foundation-quality-loop`: Foundation quality, provenance, feedback, policy, learning, and regression guard contracts.
- `business-layer-final-target-pipelines`: Final-target Signal/Extraction/Relation/Analysis/Output pipeline contracts and DTO fields.
- `business-board-final-target-runtime`: Policy-aware board services and BoardRunResult outputs for AI News, Project Radar, Paper Radar, and Community Pulse.
- `business-cross-board-intelligence`: Cross-board relation views, technology journeys, radar, insights, and blocking rules.
- `business-interface-board-contracts`: Interface-level board contracts and dependency boundaries.

### Modified Capabilities
- None.

## Impact

- Affected code: `business/foundation`, `business/layers`, `business/boards`, `interfaces`, and `tests/business`.
- Public API impact: board services expose final-target `BoardRunResult` data while preserving existing `BoardOutput` flows where already used.
- Dependency impact: no new runtime dependency; deterministic rules are used for target-state scoring and regression checks.
- Boundary impact: no `business/evolution`, no bypass runner, no board-specific feedback/policy duplicates, no concrete storage imports in business-layer target code.
