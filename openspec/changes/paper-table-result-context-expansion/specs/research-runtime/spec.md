## ADDED Requirements

### Requirement: Research RAG Table Evidence Expansion
Research runtime SHALL expose retrieval evidence that connects table chunks to result and conclusion paragraphs when deterministic table-context metadata exists.

#### Scenario: User asks what experimental results show
- **WHEN** a result-oriented user query retrieves one or more table chunks
- **THEN** the retrieval result MUST include bounded table context expansion candidates
- **AND** each expanded candidate MUST identify the table chunk and edge that caused the expansion
