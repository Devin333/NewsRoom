# paper-rag-structural-context-expander Specification

## Purpose
TBD - created by archiving change extract-structural-context-expander. Update Purpose after archive.
## Requirements
### Requirement: Structural child interleaving is delegated to an expander module
Paper RAG retrieval SHALL interleave structural child context through a dedicated structural context expander.

#### Scenario: Figure nearby context interleaves into child chunks
- **WHEN** a figure child has nearby context and the query routes to figure intent
- **THEN** the expander returns the figure followed by the nearby context with figure expansion metadata

#### Scenario: Table nearby context interleaves into child chunks
- **WHEN** a table child has nearby context and the query should expand result context
- **THEN** the expander returns the table followed by the nearby context with table expansion metadata

#### Scenario: Formula parent context interleaves into child chunks
- **WHEN** a formula child has formula parent context and the formula context gate is active
- **THEN** the expander returns formula context with formula expansion metadata
