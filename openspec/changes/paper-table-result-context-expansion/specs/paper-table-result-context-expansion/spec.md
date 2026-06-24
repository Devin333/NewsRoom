## ADDED Requirements

### Requirement: Table Hits Expand To Interpreting Context
Research retrieval SHALL expand retrieved table chunks into deterministic interpreting context so result-oriented answers can cite both table data and surrounding analysis.

#### Scenario: Table hit has nearby context
- **WHEN** a table chunk is included in retrieval results
- **THEN** retrieval MUST fetch the chunk identified by `nearby_context_chunk_id` when present
- **AND** the expanded chunk MUST be returned with metadata explaining the expansion reason

#### Scenario: Body paragraph references table
- **WHEN** a table chunk metadata contains `referenced_by_chunks`
- **THEN** retrieval MUST fetch those paragraph chunks within the configured expansion budget
- **AND** the table source locator MUST remain unchanged

#### Scenario: Row-group table hit
- **WHEN** a retrieved table chunk is a row-group chunk with `parent_table_chunk_id`
- **THEN** retrieval MUST include the parent table chunk before broader result-context expansion

### Requirement: Result Context Is Prioritized And Bounded
Research retrieval SHALL prefer result-bearing sections while keeping table evidence expansion bounded.

#### Scenario: Result-oriented question retrieves table evidence
- **WHEN** the query intent is table, numerical-result, comparison, or result-oriented
- **THEN** retrieval SHOULD prioritize chunks from experiment, analysis, result, ablation, evaluation, and conclusion sections
- **AND** it MUST deduplicate chunks by `chunk_id`

#### Scenario: Expansion budget is exhausted
- **WHEN** candidate context chunks exceed the configured expansion budget
- **THEN** retrieval MUST keep explicit table-reference and nearby-context chunks before heuristic result/conclusion chunks
