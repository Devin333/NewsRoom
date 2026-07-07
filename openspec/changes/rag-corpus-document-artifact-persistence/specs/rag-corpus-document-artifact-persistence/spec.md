## ADDED Requirements

### Requirement: Corpus ingestion persists parsed research documents
The chunk paper pipeline SHALL persist a `research_document.json` artifact for every successful paper ingestion.

#### Scenario: Paper ingestion runs without visual descriptions
- **WHEN** `ChunkPaperPipeline.run` parses and chunks a paper without a visual describer
- **THEN** it SHALL write `research_document.json` next to the chunk manifest
- **AND** the returned result SHALL include the research document artifact path

#### Scenario: Paper ingestion runs with visual descriptions
- **WHEN** `ChunkPaperPipeline.run` enriches visual chunks with a visual describer
- **THEN** the persisted `research_document.json` SHALL include the synced visual description metadata
