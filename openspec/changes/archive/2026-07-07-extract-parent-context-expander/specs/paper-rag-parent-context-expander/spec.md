## ADDED Requirements

### Requirement: Parent context expansion is delegated to an expander module
Paper RAG retrieval SHALL expand child chunks into parent context through a dedicated parent context expander.

#### Scenario: Parent expansion returns existing metrics
- **WHEN** child chunks have parent chunk ids
- **THEN** the expander returns parent chunks plus the existing parent budget, scoring, and snippet metrics

#### Scenario: No parent falls back to children
- **WHEN** no parent chunks can be found for the child chunks
- **THEN** the expander returns the child chunks as parent context and marks parent scoring as disabled

### Requirement: Parent expander preserves scoring and snippets
The parent context expander MUST preserve current parent scoring, reranker, and snippet behavior.

#### Scenario: Long parent is converted to child-anchored snippet
- **WHEN** a parent chunk exceeds the long-parent token threshold
- **THEN** the expander returns a child-anchored snippet with the existing parent snippet metadata

#### Scenario: Parent reranker filters low scores
- **WHEN** a parent reranker is configured and a parent rerank score threshold is set
- **THEN** parents below the threshold are filtered while preserving the existing fallback to top ranked parent when all are filtered
