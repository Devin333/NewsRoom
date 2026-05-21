## Why

Cross-board path discovery currently computes path score inside path finding, which mixes graph discovery with scoring policy. This change makes path scoring and insight ranking reuse the framework scoring runtime.

## What Changes

- Add a cross-board path scoring service powered by `ScoringRuntime.score_path`.
- Keep `CrossBoardPathFinder` focused on path construction and evidence chains.
- Update insight ranking to use scored paths and carry scoring metadata.
- Add tests for path scoring, evidence gates, and insight ranking.

## Capabilities

### New Capabilities
- `cross-board-scoring-and-evidence`: Cross-board path and evidence scoring through the scoring runtime.

### Modified Capabilities

## Impact

- Affected code: `business/boards/cross_board`, existing business scoring cross-board helpers, tests.
- Public API impact: additive `CrossBoardPathScoringService`; path metadata gains scoring result.
