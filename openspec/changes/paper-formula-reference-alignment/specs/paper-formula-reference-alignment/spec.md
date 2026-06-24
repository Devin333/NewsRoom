## ADDED Requirements

### Requirement: Formula Chunks Preserve Primary Parent And Body References
Research paper formula chunks SHALL preserve one primary parent paragraph while separately recording all deterministic paragraph references to that formula.

#### Scenario: Formula has one primary parent
- **WHEN** a formula chunk is emitted
- **THEN** it MUST keep a single `parent_chunk_id` selected by the existing parent matching strategy
- **AND** it MUST record `formula_parent_match_strategy` in metadata

#### Scenario: Later paragraphs reference the same formula
- **WHEN** later paragraphs explicitly reference a known formula with text such as `Eq. (1)` or `Equation 1`
- **THEN** the formula chunk MUST include those paragraph chunk ids in `referenced_by_chunks`
- **AND** those references MUST NOT overwrite the formula chunk source locator

### Requirement: Paragraph Chunks Expose Formula References
Paragraph chunks SHALL expose deterministic formula references in metadata so downstream retrieval can expand formula evidence.

#### Scenario: Paragraph references known equation
- **WHEN** paragraph text references a known equation number or label
- **THEN** the paragraph chunk metadata MUST include `formula_references` with the matched equation id and reference text

#### Scenario: Unknown equation reference is ignored
- **WHEN** paragraph text references an equation number that is not present in the parsed document
- **THEN** no formula reference edge MUST be created for that unknown equation
