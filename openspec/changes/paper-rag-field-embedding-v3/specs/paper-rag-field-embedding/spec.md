## ADDED Requirements

### Requirement: Benchmark field embedding index

The Paper RAG benchmark live retriever SHALL build and inject a field-level embedding index for paper chunks.

#### Scenario: Live benchmark field index

- **WHEN** the benchmark loads parsed paper chunks
- **THEN** it SHALL index non-empty field texts by `paper_id`, `chunk_id`, and `field_name`
- **AND** the retriever SHALL receive the index through `field_index`

### Requirement: Expanded field text extraction

Paper field extraction SHALL expose table rows, table columns, visual descriptions, and referenced context as independent fields.

#### Scenario: Table and visual fields

- **WHEN** a table chunk has row or column metadata
- **THEN** `extract_field_texts` SHALL expose `table_rows` and `table_columns`
- **WHEN** a figure or table chunk has `visual_description`
- **THEN** `extract_field_texts` SHALL expose `visual_description`

### Requirement: Field embedding report observability

Paper RAG evaluation reports SHALL expose field embedding usage.

#### Scenario: Non-zero field embedding scores

- **WHEN** live retrieval uses field embedding hits
- **THEN** the report SHALL include non-zero `*_embedding_score` components
- **AND** the report SHALL include a `field_embedding_distribution` grouped by best embedding field
