# business-foundation-quality-loop Specification

## Purpose
TBD - created by archiving change business-final-target-0-to-1. Update Purpose after archive.
## Requirements
### Requirement: Native quality learning-loop models
The business foundation SHALL define shared provenance, quality, feedback, policy profile, policy snapshot, policy candidate, learning signal, and regression guard models that can be imported without layers, boards, interfaces, or infrastructure.

#### Scenario: Foundation imports learning-loop contracts
- **WHEN** a caller imports the learning-loop models from `business.foundation`
- **THEN** the import succeeds without importing business layers, boards, interfaces, or concrete infrastructure

### Requirement: Traceable quality and feedback
Business quality checks and feedback events MUST preserve evidence, trace, manifest, target object, board, layer, severity, status, and policy profile references when supplied.

#### Scenario: Feedback records target and evidence
- **WHEN** a board emits a feedback candidate for a failed quality check
- **THEN** the event includes target object, feedback type, severity, board or layer, evidence or trace reference, and status

### Requirement: Manual policy activation lifecycle
Policy candidates MUST be generated from learning signals and MUST NOT become active unless regression guard passes and manual activation is requested.

#### Scenario: Blocked candidate cannot activate
- **WHEN** a policy candidate has a blocking regression guard result
- **THEN** policy activation refuses to mark the candidate active

