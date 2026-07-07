# rag-answer-span-citation-gate Specification

## Purpose
TBD - created by archiving change rag-answer-span-citation-gate. Update Purpose after archive.
## Requirements
### Requirement: RAG answer claims carry source spans
Harness RAG answer candidates SHALL allow each non-abstained answer claim to carry span references for the evidence used to support that claim.

#### Scenario: Claim serializes span references
- **WHEN** a grounded answer claim is serialized
- **THEN** the serialized claim includes its `span_refs`

### Requirement: RAG answer gate verifies claim spans
Harness RAG SHALL deterministically reject non-abstained answer candidates whose claims cite missing, unknown, or mismatched span references.

#### Scenario: Claim span belongs to cited evidence
- **WHEN** a non-abstained answer claim cites an evidence id and a span reference from that evidence
- **THEN** the RAG answer gate passes span citation integrity

#### Scenario: Claim omits span references
- **WHEN** a non-abstained answer claim cites evidence ids but has no span references
- **THEN** the RAG answer gate fails span citation integrity

#### Scenario: Claim cites a span outside its evidence ids
- **WHEN** a non-abstained answer claim cites one evidence id but uses a span reference from another verified evidence item
- **THEN** the RAG answer gate fails span citation integrity

#### Scenario: Abstention has no spans
- **WHEN** an answer candidate is a valid abstention
- **THEN** the RAG answer gate does not require claim span references

### Requirement: Paper RAG service exposes verified citation spans
Paper RAG gated answer responses SHALL expose the verified span references associated with each returned citation.

#### Scenario: Citation payload includes spans
- **WHEN** Paper RAG returns a gated answer with verified citations
- **THEN** each citation payload includes the span references used by the answer claims for that evidence
