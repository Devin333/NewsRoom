## ADDED Requirements

### Requirement: Field Text Is Extracted Consistently
Research retrieval SHALL derive stable field text from existing `PaperChunk` data before field-level indexing or scoring.

#### Scenario: Chunk contains multiple fields
- **WHEN** a chunk has section title, abstract content, caption metadata, equation fields, or body content
- **THEN** field extraction MUST return normalized text for each available field
- **AND** it MUST expose available field names and field text source metadata

#### Scenario: Chunk lacks a field
- **WHEN** a chunk does not contain a field
- **THEN** field extraction MUST omit that field from available fields
- **AND** it MUST keep the other fields available for indexing and scoring

### Requirement: Field Embedding Index Stores Field Vectors
Research retrieval SHALL support a field-level embedding index for paper chunks.

#### Scenario: Chunks are indexed
- **WHEN** chunks are indexed into the field embedding index
- **THEN** the system MUST create one vector document per non-empty field
- **AND** each vector document MUST include `paper_id`, `chunk_id`, `field_name`, `field_text`, and source locator metadata

#### Scenario: Paper is deleted from the index
- **WHEN** field vectors for a paper are deleted
- **THEN** all field vector documents with the matching `paper_id` MUST be removed

### Requirement: Retrieval Uses Intent-Aware Field Search
Research retrieval SHALL search field vectors according to query intent.

#### Scenario: Figure or table question
- **WHEN** the query intent is `figure_query` or `table_query`
- **THEN** retrieval MUST prioritize caption and body fields for field vector search

#### Scenario: Formula question
- **WHEN** the query intent is `formula_query`
- **THEN** retrieval MUST prioritize equation and body fields for field vector search

#### Scenario: Contribution or method question
- **WHEN** the query intent is `contribution` or `concept_method`
- **THEN** retrieval MUST include title, abstract or body fields according to that intent

#### Scenario: Field hits overlap base hits
- **WHEN** field vector hits and base chunk vector hits refer to the same chunk
- **THEN** retrieval MUST merge them into one candidate
- **AND** it MUST preserve the best field embedding score and best matching field metadata

### Requirement: Structured Field Reranking Scores Candidates
Research retrieval SHALL support optional structured field reranking.

#### Scenario: Field reranker is configured
- **WHEN** child candidates are scored and a field reranker is available
- **THEN** retrieval MUST build field-labeled passages for candidates
- **AND** it MUST store `field_rerank_score`, `best_matching_field`, and `field_rerank_strategy` metadata

#### Scenario: Field reranker is unavailable or fails
- **WHEN** no field reranker exists, it raises an error, or it returns malformed output
- **THEN** retrieval MUST continue with deterministic field scoring and field embedding scores when available
- **AND** it MUST not discard all candidates due to reranker failure

### Requirement: Child Final Score Fuses Field Signals
Research retrieval SHALL compute an explainable `child_final_score` from semantic, field, position, and graph signals.

#### Scenario: Field semantic signals are available
- **WHEN** field embedding or field rerank scores exist for a candidate
- **THEN** retrieval MUST blend semantic score, field embedding score, field rerank score, position score, and graph score
- **AND** it MUST sort child candidates by `child_final_score` descending

#### Scenario: Field semantic signals are unavailable
- **WHEN** no field embedding or field rerank score exists
- **THEN** retrieval MUST fall back to semantic score, deterministic field score, position score, and graph score
- **AND** returned metadata MUST identify the fallback scoring strategy

### Requirement: Field-Level Retrieval Is Observable
Research retrieval SHALL expose field-level scoring and retrieval diagnostics.

#### Scenario: Retrieval returns child evidence
- **WHEN** child chunks are returned as retrieval results or evidence packs
- **THEN** metadata MUST include deterministic field scores, field embedding scores, field rerank scores, best matching field, graph score, and final score components when available

#### Scenario: Retrieval completes
- **WHEN** retrieval finishes
- **THEN** retrieval metadata MUST include whether field embedding and field reranking were enabled, field hit counts, hits by field name, top field embedding score, top field rerank score, and observed best matching fields
