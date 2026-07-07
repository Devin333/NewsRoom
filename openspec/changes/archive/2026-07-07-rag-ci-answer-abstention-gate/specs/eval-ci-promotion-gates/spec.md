## MODIFIED Requirements

### Requirement: Paper RAG CI eval gate runs real retrieval evaluation
The system SHALL provide a deterministic CI gate that runs the existing Paper RAG live retrieval evaluation path against a generated parsed-paper mini corpus.

#### Scenario: Gate includes expected-abstain samples
- **WHEN** the CI eval gate builds its deterministic mini corpus
- **THEN** the generated golden set SHALL include answerable samples
- **AND** it SHALL include expected-abstain samples
- **AND** retrieval thresholds SHALL continue to evaluate answerable samples without treating expected-abstain samples as missed gold evidence

### Requirement: Paper RAG CI eval gate enforces retrieval thresholds
The system SHALL fail the CI eval gate when configured retrieval or answer thresholds are not met.

#### Scenario: Default answer thresholds pass on healthy mini corpus
- **WHEN** the CI eval gate runs against the deterministic mini corpus
- **THEN** answer abstention accuracy SHALL be at least `0.90`
- **AND** answer success rate SHALL be at least `0.90`

#### Scenario: Answer threshold regression fails the gate
- **WHEN** a caller configures an answer threshold higher than the mini corpus result
- **THEN** the CI eval gate SHALL return a non-zero exit code
- **AND** the written report SHALL describe the failed answer threshold

### Requirement: Paper RAG CI eval gate writes promotion gate artifacts
The system SHALL write promotion gate artifacts that summarize PR-level retrieval and answer metrics against promotion-oriented checks.

#### Scenario: Promotion report includes abstention checks
- **WHEN** the CI eval gate completes
- **THEN** the promotion report SHALL include a check proving expected-abstain samples are present
- **AND** it SHALL include checks for answer abstention accuracy and answer success rate
