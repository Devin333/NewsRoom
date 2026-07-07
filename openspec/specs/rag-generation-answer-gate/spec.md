# rag-generation-answer-gate Specification

## Purpose
TBD - created by archiving change rag-generation-phase-and-answer-gate. Update Purpose after archive.
## Requirements
### Requirement: Harness RAG can generate gated answers
Harness RAG SHALL support an optional generation phase that turns a verified context pack into a grounded answer candidate and verifies it with deterministic gates.

#### Scenario: Generation disabled preserves context-pack behavior
- **WHEN** a RAG session does not enable generation policy
- **THEN** the controller SHALL return the verified context pack with the existing succeeded status
- **AND** it SHALL NOT call an answer worker

#### Scenario: Verified answer returns answered status
- **WHEN** generation policy is enabled
- **AND** an answer worker returns a candidate with non-empty answer text, valid citations, and claims with evidence ids from the context pack
- **THEN** the controller SHALL return status `answered`
- **AND** the session result SHALL include the verified answer candidate

#### Scenario: Invalid answer abstains
- **WHEN** generation policy is enabled
- **AND** the answer candidate fails deterministic answer gates
- **THEN** the controller SHALL return status `abstained`
- **AND** the final decision SHALL include answer gate failure details

#### Scenario: Valid abstention returns abstained status
- **WHEN** generation policy is enabled
- **AND** the answer worker returns an abstention candidate with empty answer text
- **THEN** the controller SHALL return status `abstained`
- **AND** the answer gates SHALL pass abstention shape checks

### Requirement: Research can adapt Paper answer generation
Research SHALL provide an adapter from verified Paper RAG context packs to framework answer candidates.

#### Scenario: Paper answer worker maps context chunks to evidence ids
- **WHEN** a context pack contains accepted Paper evidence with `paper_chunk` metadata
- **THEN** the Paper answer worker SHALL call the existing `AnswerGenerator`
- **AND** it SHALL map generated context chunk ids back to context-pack evidence ids in the answer candidate citations

#### Scenario: Missing Paper chunks produce abstention
- **WHEN** a context pack does not contain enough Paper chunk metadata to build generation context
- **THEN** the Paper answer worker SHALL return an abstention candidate instead of fabricating answer evidence
