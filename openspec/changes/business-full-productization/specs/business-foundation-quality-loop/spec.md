## ADDED Requirements

### Requirement: Improvement recommendations and proposals
The business foundation SHALL model improvement recommendations, improvement proposals, approval states, override policies, improvement context, measurement, and self-improvement reports.

#### Scenario: Proposal approval gates override
- **WHEN** recommendations are converted into proposals
- **THEN** proposed proposals are not applied until they are approved, and approved proposals can be materialized as override records without changing source code

### Requirement: Durable proposal store
The business foundation SHALL provide in-memory and local JSON improvement proposal stores with save, get, list, approve, reject, and mark-applied operations.

#### Scenario: Local proposal store round trips state
- **WHEN** a proposal is saved, approved, and marked applied
- **THEN** a later read returns the updated proposal status and payload
