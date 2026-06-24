## ADDED Requirements

### Requirement: Research Visual Chunk Alignment Metadata
Research runtime SHALL expose traceable visual chunk alignment metadata for paper figures and tables so downstream RAG and reader flows can distinguish visual location, caption evidence, nearby context, and explicit body references.

#### Scenario: Chunk metadata supports evidence replay
- **WHEN** Research RAG returns a figure or table chunk
- **THEN** the chunk metadata MUST provide enough information to replay the visual evidence back to the original PDF page/bbox and caption page/bbox when those were extracted
- **AND** explicit body references MUST be represented separately from nearby context
