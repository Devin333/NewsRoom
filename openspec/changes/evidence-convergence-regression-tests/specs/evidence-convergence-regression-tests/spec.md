## ADDED Requirements

### Requirement: Business RAG evidence typing prevents false evidence convergence
Business Research RAG regressions SHALL prove that content-derived evidence typing prevents an evidence item from satisfying a different required evidence type.

#### Scenario: Method-only evidence cannot satisfy experiment requirement
- **WHEN** a Paper RAG session requires `experiment` evidence
- **AND** the business retriever returns only a method paragraph
- **THEN** the session SHALL return `insufficient_evidence`
- **AND** the gap report SHALL still list `experiment` as missing
- **AND** the accepted evidence SHALL be typed as `method`

### Requirement: Golden regressions cover expected abstention
Research RAG golden regressions SHALL preserve `expected_behavior` semantics for both legacy and explicit-abstention cases.

#### Scenario: Legacy golden rows default to answer behavior
- **WHEN** a legacy golden row lacks `expected_behavior`
- **THEN** loading it SHALL produce an `EvidenceQAPair` with `expected_behavior` set to `answer`

#### Scenario: Expected-abstention golden case produces gated abstention payload
- **WHEN** an expected-abstention golden case is evaluated through the gated paper RAG service contract
- **THEN** the payload SHALL return status `abstained`
- **AND** the payload SHALL NOT include answer text or citations
