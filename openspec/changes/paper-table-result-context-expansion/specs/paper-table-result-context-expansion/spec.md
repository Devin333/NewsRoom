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

#### Scenario: Generic experiment paragraph has no result signal
- **WHEN** a candidate paragraph only has an experiment-like section role but no result, evaluation, conclusion, quality, benchmark, or score signal in title or content
- **THEN** retrieval MUST NOT include it as heuristic table result context

#### Scenario: Reranker is available for heuristic result context
- **WHEN** a reranker is configured and heuristic table result-context candidates pass the result-signal gate
- **THEN** retrieval MUST score those candidates with a query that includes the user question and table evidence
- **AND** reranker scores MUST affect only heuristic result/conclusion ordering, not deterministic table graph edges
- **AND** expanded chunks MUST expose rerank score metadata

#### Scenario: Reranker is unavailable or fails
- **WHEN** no reranker is configured or reranking fails
- **THEN** retrieval MUST fall back to deterministic role/title/proximity ordering
