# paper-rag-retrieval-policy-trace Specification

## Purpose
TBD - created by archiving change retrieval-policy-config-and-trace. Update Purpose after archive.
## Requirements
### Requirement: Retrieval policy reports stable config hash
Paper RAG retrieval SHALL include a deterministic active policy config hash in retrieval metadata.

#### Scenario: Same policy produces same hash
- **WHEN** the same named retrieval policy is built twice
- **THEN** policy serialization produces the same hash
- **AND** retrieval metadata includes that hash

### Requirement: Retrieval degradations are structured in trace metadata
Paper RAG retrieval SHALL include structured trace metadata for degradation events.

#### Scenario: Sparse inventory is empty
- **WHEN** sparse lexical retrieval is enabled but no chunks are available
- **THEN** retrieval metadata includes `retrieval_trace.degradations`
- **AND** the existing `retrieval_degradations` compatibility field contains the same degradation entries
