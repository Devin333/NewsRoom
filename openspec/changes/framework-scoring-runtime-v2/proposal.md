## Why

The initial framework scoring runtime is functional but still organized as a flat file set. The v2 PRD requires scoring to become a classified subsystem so algorithms, gates, ranking, fusion, runtime entrypoints, adapters, and future business migration code can grow without turning `framework/scoring` into a large grab bag.

## What Changes

- Reorganize `framework/scoring` into classified subpackages while preserving existing top-level import paths as compatibility wrappers.
- Add v2 API surface for scoring errors, score/result helpers, recipe loaders, feature providers/normalizers/utilities, dict adapters, and algorithm naming.
- Extend the scoring registry to register algorithms, normalizers, and default gate specs in addition to rankers, fusions, calibrators, and explainers.
- Add `business/scoring` migration modules for board-card adapters, board/cross-board feature builders, recipe definitions, and a light scoring service.
- Add categorized framework scoring tests and business scoring migration tests.

## Capabilities

### New Capabilities

- `framework-scoring-runtime-v2`: Classified scoring runtime package layout with compatible public API, richer registry extension points, and business scoring migration helpers.

### Modified Capabilities

None.

## Impact

- Affected code: `framework/scoring`, `business/scoring`, scoring tests, `pyproject.toml`, and compatibility imports used by existing board adapter code.
- Public API impact: additive and compatibility-preserving; existing `framework.scoring` imports remain supported.
- Dependency impact: none.
