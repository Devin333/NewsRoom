## ADDED Requirements

### Requirement: Paper retrieval port uses the Research adapter metadata projection
`PaperChunkRetrievalPort` SHALL build `EvidencePack.metadata` through a Research-owned adapter helper instead of maintaining a separate inline Paper metadata mapping.

#### Scenario: Evidence metadata is projected by the adapter
- **WHEN** `PaperChunkRetrievalPort` converts a `PaperChunk` into an `EvidencePack`
- **THEN** the metadata is produced by the Research adapter projection helper
- **AND** the port preserves existing evidence id, title, summary, source refs, confidence, freshness, lineage, and retrieval ordering behavior

### Requirement: Existing Paper evidence metadata remains compatible
The Research adapter metadata projection SHALL preserve the Paper-specific metadata fields previously exposed by `PaperChunkRetrievalPort`.

#### Scenario: Formula evidence keeps formula metadata
- **WHEN** a formula `PaperChunk` is converted into an `EvidencePack`
- **THEN** `chunk_type`, `parent_chunk_id`, `has_formula`, `formula_latex`, `page`, and `pdf_rect` remain available in metadata

#### Scenario: Visual evidence keeps visual diagnostics
- **WHEN** a figure or table `PaperChunk` is converted into an `EvidencePack`
- **THEN** image refs, OCR diagnostics, visual/text/fused scores, content source metadata, row ranges, and caption locators remain available when provided by the chunk

### Requirement: Paper evidence exposes kernel metadata
The Research adapter metadata projection SHALL expose kernel evidence metadata in the same naming style used by Harness kernel adapters.

#### Scenario: Kernel metadata is available on evidence packs
- **WHEN** a `PaperChunk` has a source locator and score metadata
- **THEN** the converted `EvidencePack.metadata` includes `rag_document_id`, `rag_chunk_id`, `rag_score`, `rag_score_breakdown`, and `rag_source_locator`
- **AND** those values are derived from the `PaperChunk -> RAGEvidence` adapter path

### Requirement: Framework RAG remains domain-neutral
This migration SHALL NOT introduce Research, Paper, PDF parser, Nougat, or Surya dependencies into `framework/rag`.

#### Scenario: Framework boundary scan stays clean
- **WHEN** `framework/rag` files are scanned for Research imports and paper parser terms
- **THEN** the scan finds no Research dependency or paper parser concept leakage
