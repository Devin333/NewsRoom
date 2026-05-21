## MODIFIED Requirements

### Requirement: Board policy-aware ranking
Board ranking rules MUST consume versioned policy profiles and output board-specific ranking features plus a human-readable ranking reason. AI News, Project Radar, Paper Radar, and Community Pulse MUST NOT all use the same generic feature set for top-card ranking.

#### Scenario: Ranking reason emitted
- **WHEN** a board card is presented
- **THEN** the card includes ranking features and a non-empty ranking reason

#### Scenario: Board rankings differ by business purpose
- **WHEN** the same normalized signal batch is processed by the four board services
- **THEN** each board emits ranking features and ranking reasons that reflect that board's policy focus

## ADDED Requirements

### Requirement: Board-specific presentation and quality
Each board service SHALL apply its own presenter and quality checks before returning BoardRunResult while preserving the shared output DTO contract.

#### Scenario: Presented board result contains board semantics
- **WHEN** a board run result is built
- **THEN** cards include board-specific badges, metrics or metadata, quality checks, evidence refs, and policy-compatible ranking reasons
