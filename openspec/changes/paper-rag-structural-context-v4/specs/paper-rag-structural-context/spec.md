## ADDED Requirements

### Requirement: Structured answer context roles

Paper RAG answer context assembly SHALL classify selected context chunks by role.

#### Scenario: Primary and interpretation contexts

- **WHEN** a selected context chunk is a retrieved figure, table, formula, or direct child evidence
- **THEN** its role SHALL be `primary_evidence`
- **WHEN** a selected context chunk is added through nearby, referenced, result/conclusion, or parent expansion
- **THEN** its role SHALL be `interpretation_context`

### Requirement: Locator context metadata

Paper RAG answer context assembly SHALL expose locator metadata for selected contexts.

#### Scenario: Context locator payload

- **WHEN** a selected context chunk has `source_locator`, `caption_source_locator`, `image_ref`, `page`, `pdf_rect`, or `caption_pdf_rect`
- **THEN** answer context metadata SHALL include a `locator_context` item for that chunk

### Requirement: Expanded field rendering

Paper RAG answer generation SHALL include expanded field texts in context rendering.

#### Scenario: Figure, table, and formula fields

- **WHEN** a selected table chunk has row or column field text
- **THEN** rendered context SHALL include `table_rows` and `table_columns`
- **WHEN** a selected figure chunk has `visual_description`
- **THEN** rendered context SHALL include `visual_description`
- **WHEN** a selected formula chunk has referenced explanation text
- **THEN** rendered context SHALL include `referenced_text`
