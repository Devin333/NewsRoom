# rag-live-answer-readiness-artifact Specification

## Purpose
TBD - created by archiving change rag-live-answer-readiness-artifact. Update Purpose after archive.
## Requirements
### Requirement: Live answer eval writes readiness artifacts
The system SHALL write durable readiness artifacts before running or skipping live answer evaluation.

#### Scenario: Workflow runs without LLM secrets
- **WHEN** the live answer eval workflow runs without required LLM credentials
- **THEN** it SHALL write readiness JSON and Markdown artifacts
- **AND** it SHALL upload those artifacts even though live answer eval is skipped

### Requirement: Readiness artifacts summarize corpus and credential state
The readiness artifact SHALL summarize live answer eval prerequisites without exposing secrets.

#### Scenario: Real corpus and golden set are inspected
- **WHEN** readiness is generated with a golden set path and papers directory
- **THEN** it SHALL record golden pair count, expected behavior counts, distinct paper count, papers directory existence, and parsed research document count
- **AND** it SHALL record whether fixture eval and real-corpus eval are eligible to run
- **AND** it SHALL NOT include API key values

### Requirement: Readiness command is reusable locally and in CI
The readiness check SHALL be available through a CLI path and the project dev command wrapper.

#### Scenario: Operator runs readiness locally
- **WHEN** an operator runs `python -m scripts.dev check-live-answer-readiness`
- **THEN** the command SHALL write the same artifact files used by the scheduled workflow
