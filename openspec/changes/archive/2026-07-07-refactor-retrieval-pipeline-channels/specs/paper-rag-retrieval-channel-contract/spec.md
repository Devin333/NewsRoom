## ADDED Requirements

### Requirement: Recall channels expose ranked hit contracts
Paper RAG retrieval SHALL define a common ranked hit structure for recall channels.

#### Scenario: Ranked hit carries common fields
- **WHEN** a recall channel emits a candidate
- **THEN** the candidate includes `chunk_id`, `score`, `channel`, and metadata

### Requirement: RRF fusion has one implementation
Paper RAG retrieval MUST use a single RRF fusion implementation for ranked recall lists.

#### Scenario: Existing retriever uses RRF
- **WHEN** the existing retriever performs hybrid RRF recall
- **THEN** it delegates RRF scoring to the shared fusion module
- **AND** fused chunk ordering remains deterministic for the same inputs
