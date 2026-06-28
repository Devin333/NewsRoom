# rag-harness-kernel-evidence-adapter Specification

## Purpose
TBD - created by archiving change rag-kernel-evaluation-harness-integration. Update Purpose after archive.
## Requirements
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

