# business-foundation-quality-loop Specification

## Purpose
TBD - created by archiving change business-final-target-0-to-1. Update Purpose after archive.
## Requirements
### Requirement: Native quality learning-loop models
The business foundation SHALL define shared provenance, quality, feedback, policy profile, policy snapshot, policy candidate, learning signal, regression guard, and semantic business reference models that can be imported without layers, boards, interfaces, or infrastructure.

#### Scenario: Foundation imports learning-loop contracts
- **WHEN** a caller imports the learning-loop and business ref models from `business.foundation`
- **THEN** the import succeeds without importing business layers, boards, interfaces, or concrete infrastructure

### Requirement: Traceable quality and feedback
Business quality checks and feedback events MUST preserve evidence, trace, manifest, target object, board, layer, severity, status, and policy profile references when supplied.

#### Scenario: Feedback records target and evidence
- **WHEN** a board emits a feedback candidate for a failed quality check
- **THEN** the event includes target object, feedback type, severity, board or layer, evidence or trace reference, and status

### Requirement: Manual policy activation lifecycle
Policy candidates MUST be generated from learning signals and MUST NOT become active unless regression guard passes and manual activation is requested.

#### Scenario: Blocked candidate cannot activate
- **WHEN** a policy candidate has a blocking regression guard result or no manual activation request
- **THEN** policy activation refuses to mark the candidate active

### Requirement: Runtime quality closure
Quality failures and cross-board guard failures SHALL flow into feedback events, grouped learning signals, policy candidates, and regression guard results during business workflow or final business runs.

#### Scenario: Quality failure produces policy candidate
- **WHEN** repeated board or cross-board feedback is aggregated
- **THEN** the runtime closure creates a learning signal, a policy candidate, and a regression guard result while keeping the candidate inactive

