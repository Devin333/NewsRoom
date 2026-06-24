## ADDED Requirements

### Requirement: Parent Expansion Is Budgeted
Research retrieval SHALL bound parent expansion independently from child retrieval so parent context cannot flood the evidence set.

#### Scenario: Parent candidates exceed count budget
- **WHEN** multiple retrieved child chunks point to distinct parent chunks
- **THEN** retrieval MUST return no more than the effective parent chunk budget
- **AND** it MUST deduplicate parents by `chunk_id`

#### Scenario: Parent candidates exceed token budget
- **WHEN** parent candidates exceed the configured approximate token budget
- **THEN** retrieval MUST stop adding lower-priority parents once the budget is exhausted
- **AND** retrieval metadata SHOULD expose parent budget usage

### Requirement: Long Parents Are Snippeted
Research retrieval SHALL avoid returning full long parent sections when a child-anchored snippet can preserve enough local context.

#### Scenario: Parent content is longer than threshold
- **WHEN** a parent chunk exceeds the long-parent token threshold
- **THEN** retrieval MUST return a snippet derived from that parent
- **AND** the snippet metadata MUST include the original parent id and anchor child id

#### Scenario: Child anchor is not found in parent text
- **WHEN** snippet extraction cannot locate the child content in the parent content
- **THEN** retrieval MUST use a deterministic fallback snippet
- **AND** metadata MUST record the fallback snippet strategy

### Requirement: Parent Reranking Is Optional And Traceable
Research retrieval SHALL use parent reranking when available while preserving deterministic fallback behavior.

#### Scenario: Reranker is available
- **WHEN** a reranker is configured and parent candidates exist
- **THEN** retrieval MUST score parent candidates with a query that includes the user question and child anchor content
- **AND** reranked parent chunks MUST expose rerank score metadata

#### Scenario: Reranker is unavailable or fails
- **WHEN** no reranker is configured, reranker scoring fails, or the reranker returns malformed output
- **THEN** retrieval MUST fall back to deterministic parent ordering

### Requirement: Parent Budget Depends On Query Intent
Research retrieval SHALL tune parent context volume by query intent.

#### Scenario: Method or concept query
- **WHEN** the route intent is explanatory, such as `concept_method` or `contribution`
- **THEN** retrieval SHOULD allow a larger parent budget than table or factual result queries

#### Scenario: Table or numerical result query
- **WHEN** the route intent is `table_query`, `formula_query`, `numerical_result`, or `comparison`
- **THEN** retrieval SHOULD use a tighter parent budget so table/result-specific context remains dominant
