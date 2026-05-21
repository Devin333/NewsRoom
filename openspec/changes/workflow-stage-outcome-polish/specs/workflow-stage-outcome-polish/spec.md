## ADDED Requirements

### Requirement: Skipped Stage Outcomes
Board workflow stage outcomes SHALL represent skipped stages and skip recovery metadata.

#### Scenario: Skipped stage result is serializable
- **WHEN** a skipped stage result is created
- **THEN** it has `status=skipped`, `recovery_action=skip`, a warning reason, and serializable metadata

### Requirement: Stage Evidence Metadata
Board workflow stage outcomes SHALL carry lightweight quality, feedback, and guard metadata.

#### Scenario: Stage result carries diagnostic evidence
- **WHEN** a stage result is created with quality, feedback, and guard dictionaries
- **THEN** those values are preserved in serialized output

### Requirement: Failed Stage Duration Accuracy
Board workflows SHALL record failed stage duration using the failed stage's actual start time.

#### Scenario: Stage exception records current stage
- **WHEN** a workflow stage raises an exception
- **THEN** `last_execution` records the failed current stage, its error details, and a non-negative duration measured from that stage start
