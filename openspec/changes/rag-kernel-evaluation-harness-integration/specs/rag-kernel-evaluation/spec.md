## ADDED Requirements

### Requirement: Retrieval metrics are calculated from generic evidence ids
The system SHALL provide generic retrieval metrics including Hit@K, MRR, nDCG@K, evidence coverage, context recall, and source locator coverage.

#### Scenario: Gold evidence appears in ranked results
- **WHEN** a retrieval case includes gold evidence ids and ranked evidence ids
- **THEN** the calculator reports hit, reciprocal rank, and coverage values
- **AND** the calculation does not depend on paper-specific QA types

### Requirement: Answer metrics are deterministic and grounded in provided facts
The system SHALL provide deterministic answer metrics for fact coverage, citation grounding, answer relevance, faithfulness proxy, and abstention accuracy using only supplied answer text, facts, citations, and context ids.

#### Scenario: Answer cites grounded context and covers facts
- **WHEN** an answer contains expected fact text and cites context evidence ids
- **THEN** the answer metric calculator reports positive fact coverage and citation grounding
- **AND** it does not call an LLM judge

### Requirement: Evaluation reports are serializable
The system SHALL provide scorecard and report objects that serialize metric values, failure reasons, and metadata to dict and markdown forms.

#### Scenario: Scorecard emits report
- **WHEN** retrieval and answer metric values are added to a scorecard
- **THEN** the report can be rendered as structured data and markdown

### Requirement: Failure reasons use a shared taxonomy
The system SHALL expose generic RAG failure reason constants for missing gold retrieval, low rank, context missing gold, citation missing source, low fact match, ungrounded answer, expected abstention, budget exhaustion, and reranker unavailability.

#### Scenario: Failure reason is attached to report
- **WHEN** a scorecard records a generic failure reason
- **THEN** the reason serializes with a stable machine-readable value
*** Add File: openspec/changes/rag-kernel-evaluation-harness-integration/specs/rag-harness-kernel-evidence-adapter/spec.md
## ADDED Requirements

### Requirement: Harness can consume kernel RAG evidence
The system SHALL provide a Harness-owned adapter that converts `framework.rag.core.RAGEvidence` into `framework.harness.rag.models.EvidenceCandidate`.

#### Scenario: Kernel evidence becomes Harness candidate
- **WHEN** `RAGEvidence` has text, score, source locator, and metadata
- **THEN** the adapter returns an `EvidenceCandidate` with title, summary, source ref, span refs, confidence, lineage, and metadata
- **AND** no Research imports are required

### Requirement: Kernel evidence score is preserved for Harness diagnostics
The Harness evidence adapter SHALL preserve kernel score and score breakdown in candidate metadata.

#### Scenario: Score breakdown travels to Harness metadata
- **WHEN** kernel evidence has score breakdown values
- **THEN** the resulting Harness evidence candidate metadata includes those values for diagnostics

### Requirement: Harness adapter does not change session execution
The Harness adapter SHALL be additive and MUST NOT alter `BoundedRAGSessionController` routing, gate, replan, halt, or context assembly behavior in this slice.

#### Scenario: Existing Harness RAG tests remain compatible
- **WHEN** Harness RAG tests run after the adapter is added
- **THEN** existing session behavior remains compatible
