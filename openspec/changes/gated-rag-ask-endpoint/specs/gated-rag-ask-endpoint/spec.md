## ADDED Requirements

### Requirement: Paper RAG ask can use gated answer generation
The system SHALL route generated chunk-based paper RAG answers through the bounded Harness RAG generation phase by default.

#### Scenario: Retrieve-only behavior remains compatible
- **WHEN** a caller asks paper RAG with `generate=false`
- **THEN** the service SHALL return retrieved passages and retrieval metrics
- **AND** it SHALL NOT run the gated answer worker

#### Scenario: Generated answer uses gated session
- **WHEN** a caller asks paper RAG with `generate=true` and gated generation enabled
- **THEN** the service SHALL run `PaperRAGSession` with generation policy enabled
- **AND** it SHALL return status, answer candidate, claims, citations, gate results, and transcript id

#### Scenario: Invalid or insufficient generated answer abstains
- **WHEN** the gated session cannot verify an answer candidate
- **THEN** the service SHALL return status `abstained` or `insufficient_evidence`
- **AND** it SHALL include deterministic decision and gate details instead of returning unverified answer text

#### Scenario: Explicit fallback remains available
- **WHEN** a caller asks paper RAG with `generate=true` and `gated=false`
- **THEN** the service SHALL use the legacy direct generator path
- **AND** the payload SHALL mark the generation mode as `legacy_direct`
