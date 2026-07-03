## ADDED Requirements

### Requirement: Paper RAG CI eval gate runs real retrieval evaluation
The system SHALL provide a deterministic CI gate that runs the existing Paper RAG live retrieval evaluation path against a generated parsed-paper mini corpus.

#### Scenario: Gate runs without external services
- **WHEN** the CI eval gate is executed with its default configuration
- **THEN** it SHALL build parsed paper fixtures locally
- **AND** it SHALL run live in-memory retrieval evaluation through the existing evidence evaluator
- **AND** it SHALL NOT require network, Qdrant, Postgres, or LLM credentials

#### Scenario: Evidence report is written
- **WHEN** the CI eval gate completes
- **THEN** it SHALL write `evidence_regression_report.json`
- **AND** it SHALL write `evidence_regression_report.md`
- **AND** the JSON report SHALL include retrieval metrics and configured thresholds

### Requirement: Paper RAG CI eval gate enforces retrieval thresholds
The system SHALL fail the CI eval gate when configured retrieval thresholds are not met.

#### Scenario: Default thresholds pass on healthy mini corpus
- **WHEN** the CI eval gate runs against the deterministic mini corpus
- **THEN** retrieval hit rate, evidence coverage, required evidence type coverage, source locator coverage, and MRR thresholds SHALL pass

#### Scenario: Threshold regression fails the gate
- **WHEN** a caller configures a threshold higher than the mini corpus result
- **THEN** the CI eval gate SHALL return a non-zero exit code
- **AND** the written report SHALL describe the failed threshold

### Requirement: Paper RAG CI eval gate writes promotion gate artifacts
The system SHALL write promotion gate artifacts that summarize PR-level retrieval metrics against promotion-oriented checks.

#### Scenario: Promotion report is written
- **WHEN** the CI eval gate completes
- **THEN** it SHALL write a promotion gate JSON artifact
- **AND** it SHALL write a promotion gate Markdown artifact
- **AND** each artifact SHALL include policy name, ready status, thresholds, checks, and source evidence report path

#### Scenario: Promotion failure contributes to exit code
- **WHEN** any promotion gate check fails
- **THEN** the CI eval gate SHALL return a non-zero exit code

### Requirement: Paper RAG CI eval gate is available in dev tooling and CI
The system SHALL expose the CI eval gate through the repository developer command surface and run it in GitHub CI.

#### Scenario: Developer command dispatch
- **WHEN** `python -m scripts.dev test-rag-eval-gate` is executed
- **THEN** it SHALL invoke the Paper RAG CI eval gate CLI

#### Scenario: GitHub CI runs the gate
- **WHEN** the GitHub CI workflow executes
- **THEN** it SHALL include a step that runs `python -m scripts.dev test-rag-eval-gate`
