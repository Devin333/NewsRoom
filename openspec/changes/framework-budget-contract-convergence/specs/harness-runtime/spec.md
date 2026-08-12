## ADDED Requirements

### Requirement: Canonical budget facts are deterministic Harness inputs
For Harness-managed runs, canonical budget admission, denial, settlement, release, expiry, and indeterminate facts SHALL be recorded durably before they influence a state transition. The budget ledger MUST NOT select workflow routing. Harness SHALL map validated budget facts and policy to only its bounded controlled outcomes and SHALL record that transition separately from the resource fact.

#### Scenario: Budget denial is recorded before halt
- **WHEN** a worker operation is denied by a canonical budget ceiling
- **THEN** the denial fact and deterministic budget projection are durably recorded
- **AND** Harness selects and records the allowed retry, replan, approval, halted, or failed outcome
- **AND** no LLM-provided route suggestion participates in that decision

#### Scenario: Indeterminate usage cannot continue silently
- **WHEN** provider dispatch may have consumed budget but terminal usage cannot be confirmed
- **THEN** Harness enters a controlled reconciliation, approval, halted, or failed path within existing bounds
- **AND** it does not release capacity, repeat dispatch, publish, or write memory based on diagnostics alone
