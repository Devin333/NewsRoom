## ADDED Requirements

### Requirement: Cross-board Path Scoring Service
The business layer SHALL score cross-board paths through `ScoringRuntime.score_path`.

#### Scenario: Scored path carries scoring result
- **WHEN** a cross-board path is scored
- **THEN** `path_score`, confidence, blocking reasons, and metadata reflect the scoring result

### Requirement: Path Finder Delegates Scoring
Path finding SHALL build candidate paths and delegate final path scoring to the path scoring service.

#### Scenario: Path finder returns scored paths
- **WHEN** path finder discovers paths
- **THEN** returned paths are sorted by runtime-derived path score

### Requirement: Insight Ranking Uses Path Score
Cross-board insight ranking SHALL use scored path values and preserve scoring metadata.

#### Scenario: Blocked paths are penalized
- **WHEN** a path has blocking reasons
- **THEN** insight ranking does not promote it as high-priority
