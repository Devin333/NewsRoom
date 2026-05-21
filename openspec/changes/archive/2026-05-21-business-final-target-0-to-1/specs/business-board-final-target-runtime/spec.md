## ADDED Requirements

### Requirement: Board vertical slice runtime
Each of AI News, Project Radar, Paper Radar, and Community Pulse SHALL expose models, policies, ranking rules, presenter, workflow, and board service modules.

#### Scenario: Board modules are importable
- **WHEN** the four board package modules are imported
- **THEN** each board exposes PRD-required runtime module names without importing concrete storage

### Requirement: BoardRunResult contract
Each board service SHALL be able to return a BoardRunResult containing cards, detail pages, insights, reports, policy snapshot, quality summary, feedback candidates, trace ref, and manifest ref.

#### Scenario: Board run produces quality evidence
- **WHEN** a board is built from sample raw inputs
- **THEN** the result includes cards with ranking reasons and evidence refs plus a policy snapshot and quality summary

### Requirement: Board policy-aware ranking
Board ranking rules MUST consume versioned policy profiles and output ranking features plus a human-readable ranking reason.

#### Scenario: Ranking reason emitted
- **WHEN** a board card is presented
- **THEN** the card includes ranking features and a non-empty ranking reason
