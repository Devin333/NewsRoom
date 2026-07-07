## ADDED Requirements

### Requirement: Cross-reference expansion is delegated to an expander module
Paper RAG retrieval SHALL expand child chunks into reference context through a dedicated cross-reference context expander.

#### Scenario: Explicit chunk reference is expanded
- **WHEN** a child chunk has a first-level reference to another chunk
- **THEN** the expander returns the referenced chunk with `chunk_reference` expansion metadata

#### Scenario: Page visual related chunk is expanded
- **WHEN** a page visual child chunk lists related visual chunks
- **THEN** the expander returns those visual chunks with `page_visual_related_chunk` expansion metadata

#### Scenario: Formula reverse context is expanded
- **WHEN** another chunk points back to a formula child chunk
- **THEN** the expander returns that chunk with formula reverse expansion metadata

### Requirement: Cross-reference expansion preserves source locator inheritance
The cross-reference context expander MUST preserve existing source locator inheritance behavior.

#### Scenario: Referenced chunk lacks locator
- **WHEN** a referenced chunk lacks a source locator and the source child has one
- **THEN** the returned reference chunk inherits the source locator metadata
