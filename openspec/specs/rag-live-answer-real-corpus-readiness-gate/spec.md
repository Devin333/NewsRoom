# rag-live-answer-real-corpus-readiness-gate Specification

## Purpose
TBD - created by archiving change rag-live-answer-real-corpus-readiness-gate. Update Purpose after archive.
## Requirements
### Requirement: Real-corpus live answer eval uses readiness eligibility as a gate
The workflow SHALL NOT run real-corpus live answer evaluation unless readiness reports real-corpus eligibility.

#### Scenario: Parsed papers directory exists but golden-set coverage is incomplete
- **WHEN** the live answer workflow has LLM secrets and `.newsroom/papers` exists
- **AND** readiness reports missing paper ids from the real corpus
- **THEN** the workflow SHALL skip real-corpus live answer eval
- **AND** it SHALL leave readiness artifacts for diagnosis

### Requirement: Readiness command supports eligibility gate mode
The readiness command SHALL support non-zero exit codes when callers require a specific eligibility target.

#### Scenario: Operator requires real-corpus readiness
- **WHEN** an operator runs `python -m scripts.dev check-live-answer-readiness --require-real-corpus`
- **AND** real-corpus eligibility is false
- **THEN** the command SHALL write readiness artifacts
- **AND** it SHALL return a non-zero exit code

#### Scenario: Operator runs diagnostic readiness
- **WHEN** an operator runs `python -m scripts.dev check-live-answer-readiness` without a required eligibility flag
- **THEN** the command SHALL write readiness artifacts
- **AND** it SHALL return zero even if live eval is not ready
