## ADDED Requirements

### Requirement: Board intelligence quality feedback
Board and cross-board quality failures SHALL be converted into feedback events and learning signals that can produce policy candidates without activating them automatically.

#### Scenario: Quality failure creates manual candidate
- **WHEN** a board or cross-board run has blocking or warning quality checks
- **THEN** feedback aggregation can build a learning signal and policy candidate with manual activation status
