## ADDED Requirements

### Requirement: Domain-neutral RAG core contracts
The system SHALL provide a `framework/rag/core` package with domain-neutral DTOs for chunks, queries, evidence, source locators, and score breakdowns. These contracts MUST NOT import `business.research` modules or paper-specific parser models.

#### Scenario: Core contracts import without Research
- **WHEN** `framework.rag.core` is imported
- **THEN** the import succeeds without importing `business.research`
- **AND** the exported DTOs can be constructed with generic document, chunk, field, metadata, and locator values

### Requirement: RAG chunks preserve generic fields and metadata
The system SHALL represent retrievable content as `RAGChunk` with `chunk_id`, `document_id`, `text`, `chunk_type`, `fields`, optional `source_locator`, and `metadata`.

#### Scenario: Generic chunk carries structured and pass-through data
- **WHEN** a `RAGChunk` is created with field text, source locator, and metadata
- **THEN** the chunk exposes the typed identifiers and text
- **AND** the metadata remains available without domain-specific conversion

### Requirement: RAG evidence records explainable scores
The system SHALL represent retrieved evidence as `RAGEvidence` with a numeric `score`, optional `source_locator`, and a score breakdown that can preserve child, parent, field, section, position, rerank, and final score components.

#### Scenario: Evidence exposes score breakdown
- **WHEN** retrieved evidence is created with a score breakdown
- **THEN** downstream code can inspect each named score component
- **AND** missing score components are treated as absent rather than fabricated

### Requirement: RAG core ports are protocol-based
The system SHALL define protocol-style ports for chunk storage, retrieval, reranking, and context assembly so business adapters can implement framework contracts without inheriting concrete framework classes.

#### Scenario: Business adapter satisfies retrieval contract
- **WHEN** an adapter implements the required retrieve method shape
- **THEN** it can satisfy the framework retrieval port contract structurally
- **AND** framework code does not need to import the adapter's business module

### Requirement: Framework RAG boundary excludes paper parsing concepts
The system SHALL keep `framework/rag` free of Paper RAG parser concepts such as `PaperChunk`, arXiv-specific parsing, Nougat, Surya, and PDF extraction logic.

#### Scenario: Boundary scan passes
- **WHEN** the framework RAG package is scanned for Research imports and paper parser terms
- **THEN** no production framework RAG file contains those forbidden dependencies or concepts
*** Add File: openspec/changes/rag-kernel-core-contracts/specs/paper-rag-kernel-adapter/spec.md
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
