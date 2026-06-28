## ADDED Requirements

### Requirement: Paper chunks project to RAG chunks
The system SHALL provide a Research-owned adapter that maps `PaperChunk` instances into `framework.rag.core.RAGChunk` instances without moving `PaperChunk` into framework code.

#### Scenario: Paragraph chunk is projected
- **WHEN** a paragraph `PaperChunk` is adapted
- **THEN** the resulting `RAGChunk` uses the paper id as `document_id`
- **AND** the chunk content becomes `text`
- **AND** section, formula, figure, table, and reference metadata remain available through fields or metadata

### Requirement: Paper source locators are preserved
The Paper adapter SHALL preserve the original paper source locator string and SHALL parse common page and PDF rectangle metadata into a generic `SourceLocator` when those values are available.

#### Scenario: PDF locator projects to generic locator
- **WHEN** a `PaperChunk` has source locator metadata with page and rectangle information
- **THEN** the adapted `RAGChunk` includes a `SourceLocator`
- **AND** the original locator string remains available for citation and debugging

### Requirement: Paper evidence projection keeps score metadata
The Paper adapter SHALL be able to project a `PaperChunk` into `RAGEvidence` while preserving existing score-related metadata as an explainable score breakdown.

#### Scenario: Chunk score metadata becomes evidence breakdown
- **WHEN** a `PaperChunk` contains child, parent, field, section, position, rerank, or final score metadata
- **THEN** the adapted `RAGEvidence` exposes those values in `score_breakdown`
- **AND** the adapter does not invent score values that were not present

### Requirement: Adapter does not change Paper RAG behavior
The Paper adapter SHALL be additive in this slice and MUST NOT change existing `ResearchRetriever`, benchmark ranking, visual description, or Harness `EvidencePack` behavior.

#### Scenario: Existing retrieval path remains intact
- **WHEN** existing Paper RAG tests run after the adapter is added
- **THEN** retrieval and evaluation behavior remains compatible with the pre-adapter path
- **AND** callers that still use `PaperChunkRetrievalPort` continue to receive `EvidencePackCollection`

### Requirement: Adapter boundary stays in Research
The Paper adapter SHALL live under `business/research/rag/adapters` and framework code MUST NOT import it.

#### Scenario: Framework does not import Paper adapter
- **WHEN** `framework/rag` files are scanned
- **THEN** they do not import `business.research.rag.adapters`
- **AND** all `PaperChunk` references remain in Research code or tests
