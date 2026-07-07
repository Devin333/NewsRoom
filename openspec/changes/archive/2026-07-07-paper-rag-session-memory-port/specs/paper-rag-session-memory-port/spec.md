## ADDED Requirements

### Requirement: Paper RAG session accepts a harness memory port
`PaperRAGSession` SHALL accept an optional `MemoryPort` and pass it into `BoundedRAGSessionController`.

#### Scenario: Memory port is injected
- **WHEN** `PaperRAGSession` is constructed with a memory port
- **THEN** the session SHALL pass that memory port to `BoundedRAGSessionController`

#### Scenario: Memory port is absent
- **WHEN** `PaperRAGSession` is constructed without a memory port
- **THEN** current no-memory behavior SHALL remain unchanged

### Requirement: Research RAG memory adapter maps MemoryRuntime recall hits
The Research RAG layer SHALL provide an adapter from `MemoryRuntime` to the harness `MemoryPort` recall contract.

#### Scenario: Episodic memory recall succeeds
- **WHEN** the adapter recalls memories for an allowed namespace
- **THEN** it SHALL return hit dictionaries with `namespace`, `memory_ref`, `memory_id`, `content`, and `relevance`
- **AND** it SHALL only include recalled memories from the requested namespace

#### Scenario: Memory writes are not committed by this adapter
- **WHEN** the adapter receives a memory write commit request
- **THEN** it SHALL not mutate the underlying memory runtime
- **AND** it SHALL return a rejected write candidate explaining that the adapter is recall-only

### Requirement: Production paper RAG factory can opt into memory
The production paper RAG factory SHALL build a memory port for `PaperRAGSession` only when memory is explicitly enabled.

#### Scenario: Memory env is enabled
- **WHEN** `NEWS_RAG_MEMORY` is truthy
- **THEN** `build_paper_rag_session()` SHALL pass a memory port into `PaperRAGSession`

#### Scenario: Memory env is disabled
- **WHEN** `NEWS_RAG_MEMORY` is absent or false
- **THEN** `build_paper_rag_session()` SHALL pass no memory port

### Requirement: Vector memory store preserves namespaces
Vector-backed memory storage SHALL preserve and filter `MemoryRecord.namespace`.

#### Scenario: Namespaced memory record is recalled
- **WHEN** a namespaced `MemoryRecord` is written through `VectorMemoryStoreAdapter`
- **THEN** fetching or searching the record SHALL preserve its namespace
- **AND** namespace-scoped search SHALL not return records from another namespace
