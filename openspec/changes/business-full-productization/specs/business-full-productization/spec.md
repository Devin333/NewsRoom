## ADDED Requirements

### Requirement: Productized primary board runs
Each primary business board SHALL expose an independent productized workflow, runner, artifact publisher, subscription payload, feedback loop, improvement recommendations, and eval cases while preserving existing board service behavior.

#### Scenario: Board run publishes product artifacts
- **WHEN** a productized primary board runner is invoked with offline signals
- **THEN** it returns a workflow RunResult and writes board output, cards, detail pages, insights, quality summary, subscription payload, feedback events, learning signals, recommendations, proposals, applied overrides, improvement measurement, summary markdown, and manifest artifacts

### Requirement: Business skill runtime integration
The business layer SHALL provide an offline-capable BusinessSkillRuntime that can call an injected SkillRunner or deterministic fallbacks for entity extraction, source reliability, event deduplication, evidence checking, report writing, and trend analysis.

#### Scenario: Skill failure falls back
- **WHEN** an injected skill runner returns a non-fatal failure
- **THEN** the board workflow continues with deterministic fallback output and records structured warning and skill trace metadata

### Requirement: Subscription-ready board payloads
Each primary board SHALL produce a SubscriptionPayload with non-empty targets, board-specific tags, source types, mapped cards, summary, quality score, and delivery hints.

#### Scenario: Board subscription payload contains routing data
- **WHEN** a board output contains cards and entities
- **THEN** the subscription payload includes board tags, source types, entities, cards, summary, quality score, and delivery hints suitable for downstream delivery planning

### Requirement: Approval-gated improvement loop
The business feedback loop SHALL convert quality results to feedback events, learning signals, recommendations, proposals, approved overrides, next-run application context, measurement, and a self-improvement report without editing source code.

#### Scenario: Approved proposal affects next run
- **WHEN** an improvement proposal is approved before a subsequent board run
- **THEN** the next run records the applied override and includes before/after measurement data in artifacts

### Requirement: Board eval matrix
The business evaluation package SHALL provide at least five offline eval cases for each primary board and an eval runner/report that checks card count, quality score, ranking relevance, evidence coverage, subscription tags, improvement recommendations, and unhandled errors.

#### Scenario: Eval suite runs offline
- **WHEN** the board eval suite runs without network or LLM access
- **THEN** it returns per-case results and a report with pass/fail, score, failures, and metrics
