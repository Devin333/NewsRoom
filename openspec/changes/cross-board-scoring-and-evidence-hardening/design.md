## Context

The scoring runtime already supports graph path scoring. Business cross-board code should provide path-specific features and recipes while preserving graph construction behavior.

## Design

- `CrossBoardPathScoringService` converts a `CrossBoardPath` to target/features/recipe and calls `ScoringRuntime.score_path`.
- Path score, confidence, blocking reasons, and metadata are updated from `ScoringResult`.
- `CrossBoardPathFinder` builds paths and guard results, then delegates final scoring.
- `CrossBoardInsightRanker` relies on `path.path_score` and copies scoring metadata into insight metadata.

## Constraints

- Do not rewrite graph builder or evidence chain builder.
- Do not introduce business imports into framework scoring.
