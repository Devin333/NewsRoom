## MODIFIED Requirements

### Requirement: Paper chunks project to RAG chunks
The system SHALL provide a Research-owned adapter that maps `PaperChunk` instances into `framework.rag.core.RAGChunk` instances without moving `PaperChunk` into framework code.

#### Scenario: Paragraph chunk is projected
- **WHEN** a paragraph `PaperChunk` is adapted
- **THEN** the resulting `RAGChunk` uses the paper id as `document_id`
- **AND** the chunk content becomes `text`
- **AND** section, formula, figure, table, and reference metadata remain available through fields or metadata

#### Scenario: Structural evidence type metadata is preserved
- **WHEN** a `PaperChunk` is projected into `RAGEvidence`
- **THEN** the evidence metadata SHALL preserve `chunk_type`
- **AND** the evidence metadata SHALL preserve `section_role` as a list of role strings
