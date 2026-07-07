## ADDED Requirements

### Requirement: Chunk store exposes paper scoped chunk listing
Paper RAG chunk stores SHALL expose an explicit paper-scoped `list_chunks(paper_id)` operation through `ChunkStorePort`.

#### Scenario: Production adapter lists indexed paper chunks
- **WHEN** chunks are indexed through the production-style `PaperChunkStoreAdapter`
- **THEN** calling `list_chunks` for that paper returns the indexed `PaperChunk` objects
- **AND** chunks from other papers are not returned

### Requirement: Sparse retrieval uses the explicit chunk listing contract
Paper RAG sparse lexical retrieval MUST use `ChunkStorePort.list_chunks` directly and MUST NOT discover chunk inventories through private attributes or reflection.

#### Scenario: Sparse recall is active without private store attributes
- **WHEN** the retriever is wired with a chunk store that exposes `list_chunks` but no public or private chunk dictionary
- **THEN** a hybrid sparse query can recall an exact lexical match
- **AND** the result metadata records `sparse_recalled` greater than zero

### Requirement: Sparse inventory degradation is observable
Paper RAG retrieval SHALL record an observable degradation when sparse lexical recall is enabled but no paper chunk inventory is available.

#### Scenario: Sparse inventory is empty
- **WHEN** sparse lexical retrieval is enabled for a paper and `list_chunks` returns no chunks
- **THEN** retrieval completes without crashing
- **AND** the result metadata includes a degradation entry identifying the empty sparse inventory
