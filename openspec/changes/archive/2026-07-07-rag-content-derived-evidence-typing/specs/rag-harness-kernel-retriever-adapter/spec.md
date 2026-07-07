## MODIFIED Requirements

### Requirement: Harness adapts generic RAG retrievers
Harness RAG SHALL provide an adapter from a generic `RAGRetrieverPort` to the existing Harness `RetrievalPort`.

#### Scenario: Harness request is converted into RAG query
- **WHEN** the adapter receives a Harness retrieval request
- **THEN** it converts query, limit, filters, context refs, intent, required chunk types, and preferred fields into a `RAGQuery`
- **AND** the adapter returns a Harness `EvidencePackCollection`

#### Scenario: Resolver assigns evidence type from retrieved metadata
- **WHEN** the adapter is configured with an `EvidenceTypeResolver`
- **AND** retrieved `RAGEvidence.metadata` contains a resolver-recognized content signal
- **THEN** the resulting Harness evidence candidate SHALL use the resolved evidence type
- **AND** its metadata SHALL include `evidence_type_source` set to `content_resolved`

#### Scenario: Resolver fallback is explicit
- **WHEN** the adapter is configured with an `EvidenceTypeResolver`
- **AND** retrieved `RAGEvidence.metadata` does not contain a resolver-recognized content signal
- **THEN** the resulting Harness evidence candidate SHALL use the request/default evidence type
- **AND** its metadata SHALL include `evidence_type_source` set to `requested_fallback`

#### Scenario: Adapter remains compatible without resolver
- **WHEN** the adapter is not configured with an `EvidenceTypeResolver`
- **THEN** the resulting Harness evidence candidates SHALL keep using the request/default evidence type
- **AND** their metadata SHALL include `evidence_type_source` set to `requested_default`

### Requirement: Paper Harness retrieval port uses kernel adapter path
The existing Paper Harness retrieval port SHALL delegate through the kernel retriever adapter path while keeping Paper-facing output compatible.

#### Scenario: Existing Paper retrieval output remains compatible
- **WHEN** `PaperChunkRetrievalPort.retrieve()` is called
- **THEN** it returns the same Paper evidence ids and key metadata fields as before
- **AND** collection metadata still includes intent, child count, ref count, and section index

#### Scenario: Paper retrieval uses Research evidence type resolver
- **WHEN** `PaperChunkRetrievalPort.retrieve()` returns Paper evidence
- **AND** the Paper evidence metadata contains `section_role` or `chunk_type`
- **THEN** the Harness evidence pack metadata SHALL expose an evidence type derived from Research mapping
- **AND** the metadata SHALL include `evidence_type_source` set to `content_resolved`
