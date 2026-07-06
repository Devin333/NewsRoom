## MODIFIED Requirements

### Requirement: Business research does not depend on interface layers
The system SHALL keep `business/research` free of direct imports from `interfaces`, including business-owned RAG evaluation CLIs.

#### Scenario: Live answer eval uses business-owned assembly
- **WHEN** `run_evidence_eval --live-answer-eval` runs with parsed paper chunks from `--papers-dir`
- **THEN** the live answer ask callable is assembled from business-owned RAG session components without importing `interfaces`
- **AND** answer evaluation receives gated Harness payload semantics for conversion into `EvidenceAnswerSample`

#### Scenario: Live answer eval without fixture chunks fails closed
- **WHEN** `run_evidence_eval --live-answer-eval` is requested without parsed fixture chunks and no outer-layer ask callable is injected
- **THEN** the command fails with a clear configuration error instead of importing `interfaces` or production stores from `business/research`
