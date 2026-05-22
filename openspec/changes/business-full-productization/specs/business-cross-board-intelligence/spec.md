## ADDED Requirements

### Requirement: Productized cross-board aggregation
Cross-board intelligence SHALL aggregate productized board outputs, cards, quality summaries, subscription payloads, and improvement recommendations from the four primary boards.

#### Scenario: Cross-board aggregation includes product surfaces
- **WHEN** productized outputs for the four primary boards are available
- **THEN** cross-board intelligence returns a summary, shared entities, shared trends, conflicting signals, board coverage, recommendations, subscription payload, and improvement report

### Requirement: Weekly trend productization
Weekly intelligence SHALL add trend, historian, quality, subscription, and improvement outputs while preserving existing runner inputs and return type.

#### Scenario: Weekly runner publishes additive artifacts
- **WHEN** WeeklyIntelligenceRunner runs from persisted daily reports
- **THEN** it keeps existing report outputs and additionally publishes weekly trends, timeline, quality, subscription payload, and improvement report artifacts
