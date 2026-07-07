## MODIFIED Requirements

### Requirement: Paper RAG CI eval gate is available in dev tooling and CI
The system SHALL expose the CI eval gate through the repository developer command surface and run it in GitHub CI.

#### Scenario: Live Paper RAG E2E runs outside PR CI
- **WHEN** the live Paper RAG E2E workflow is triggered by schedule or manually
- **THEN** it SHALL start Postgres and Qdrant services
- **AND** it SHALL set `NEWS_RUN_LIVE_RESEARCH_E2E=1`
- **AND** it SHALL run `python -m scripts.dev test-rag-live-e2e`
- **AND** ordinary push and pull-request CI SHALL remain on the deterministic offline RAG eval gate
