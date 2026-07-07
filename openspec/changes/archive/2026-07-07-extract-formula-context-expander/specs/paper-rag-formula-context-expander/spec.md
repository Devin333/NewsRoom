## ADDED Requirements

### Requirement: Formula structural context refs are delegated to an expander module
Paper RAG retrieval SHALL resolve formula structural context references through a dedicated formula context expander.

#### Scenario: Formula parent context is returned
- **WHEN** a formula chunk has a parent chunk and the question asks for formula explanation
- **THEN** the expander returns a `formula_parent_context` reference

#### Scenario: Formula reverse context is returned
- **WHEN** a formula query chunk references a formula through metadata or explicit references
- **THEN** the expander returns formula reverse context references

### Requirement: Formula context limits are preserved
The formula context expander MUST preserve existing per-policy formula context limits.

#### Scenario: Formula context disabled by limit
- **WHEN** `max_formula_context_chunks` is zero
- **THEN** the expander returns no formula context references
