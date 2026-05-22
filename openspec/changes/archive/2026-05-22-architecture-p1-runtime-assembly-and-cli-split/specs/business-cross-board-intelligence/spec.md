## ADDED Requirements

### Requirement: Daily intelligence workflows preserve runtime behavior
The system SHALL keep daily and agentic cross-board intelligence workflow outputs, artifact keys, profiles, and quality decisions behavior-compatible while refactoring internal runtime assembly.

#### Scenario: Daily runner execution
- **WHEN** `DailyIntelligenceRunner` runs an existing supported profile
- **THEN** the workflow result, output fields, and artifacts remain compatible

#### Scenario: Agentic runner execution
- **WHEN** `AgenticDailyIntelligenceRunner` runs an existing supported profile
- **THEN** the workflow result, output fields, and agentic artifacts remain compatible
