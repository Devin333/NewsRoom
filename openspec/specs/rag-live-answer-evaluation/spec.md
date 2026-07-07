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

#### Scenario: Context-absence phrases count as abstentions
- **WHEN** live answer generation or answer evaluation receives text stating that the provided context does not state an answer
- **OR** the text states that the provided context contains no mention of the requested information
- **THEN** the text SHALL be classified as an abstention
- **AND** expected-abstain samples using those phrases SHALL count as correct abstentions

#### Scenario: Negative presence recitations count as abstentions
- **WHEN** a live Paper answer asks whether a paper includes, specifies, reports, discusses, provides, states, mentions, describes, or contains a requested subject
- **AND** the generated answer does not explicitly abstain
- **AND** the generated answer has insufficient overlap with the requested subject terms
- **THEN** the runtime SHALL publish an abstained answer candidate instead of the unrelated generated answer
- **AND** the candidate metadata SHALL record that negative presence relevance normalization was applied

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

