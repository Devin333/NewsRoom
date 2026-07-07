# rag-live-answer-eval-workflow Specification

## Purpose
TBD - created by archiving change live-answer-eval-workflow. Update Purpose after archive.
## Requirements
### Requirement: Live answer eval has a dev command
The system SHALL provide a dev command that runs live generated-answer evidence evaluation against fixture papers.

#### Scenario: Dev command dispatches live answer eval
- **WHEN** an operator runs `python -m scripts.dev run-live-answer-eval`
- **THEN** the command invokes the live answer evaluation runner
- **AND** the runner writes evidence report artifacts under `.newsroom/eval/live-answer` by default

### Requirement: Live answer eval is scheduled and manual
The system SHALL expose a GitHub Actions workflow that can run live answer evaluation on a schedule and by manual dispatch.

#### Scenario: Workflow runs live answer eval with secrets
- **WHEN** the workflow has `OPENAI_BASE_URL` and `OPENAI_API_KEY` configured
- **THEN** it runs `python -m scripts.dev run-live-answer-eval`
- **AND** uploads the live answer evidence artifacts

#### Scenario: Workflow fails closed when secrets are absent
- **WHEN** required LLM secrets are absent
- **THEN** the workflow reports a clear skip reason instead of invoking the live LLM path
