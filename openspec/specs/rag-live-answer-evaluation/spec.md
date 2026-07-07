# rag-live-answer-evaluation Specification

## Purpose
TBD - created by archiving change live-answer-eval-nightly. Update Purpose after archive.
## Requirements
### Requirement: Evidence CLI supports live gated answer evaluation
The evidence evaluation CLI SHALL provide a live answer evaluation mode that scores generated answers from the gated Harness answer path.

#### Scenario: Running live answer evaluation
- **WHEN** `run_evidence_eval` is invoked with `--live-answer-eval`
- **THEN** answer metrics are computed from gated answer payloads rather than deterministic synthetic samples
- **AND** the evidence report metadata records `answer_eval_mode` as `live`

### Requirement: Answer evaluation modes are mutually exclusive
The evidence evaluation CLI SHALL reject simultaneous deterministic and live answer evaluation modes.

#### Scenario: Conflicting answer modes
- **WHEN** both `--deterministic-answer-eval` and `--live-answer-eval` are provided
- **THEN** the CLI fails before writing a misleading answer report

### Requirement: Deterministic PR answer checks are labeled as pipeline checks
The CI promotion checklist SHALL identify deterministic answer checks as deterministic pipeline checks.

#### Scenario: CI gate report labels deterministic answer metrics
- **WHEN** CI runs the deterministic answer evaluation path
- **THEN** promotion check labels identify the checks as deterministic answer-eval pipeline checks

### Requirement: Evidence reports identify answer evaluation mode
RAG evidence reports SHALL identify which answer evaluation mode produced answer metrics.

#### Scenario: Answer mode is recorded
- **WHEN** an evidence report is written
- **THEN** report metadata includes `answer_eval_mode`
- **AND** the value is one of `none`, `deterministic`, or `live`
