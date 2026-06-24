## Context

The chunker already creates traceable table metadata:

- Table chunks include caption, rows, `nearby_context_chunk_id`, `referenced_by_chunks`, `table_parent_match_strategy`, visual/caption regions, and source locators.
- Paragraph chunks that explicitly mention `Table 1` / `Table 2` expose `visual_references`.
- Long tables can emit row-group chunks with `parent_table_chunk_id`.

The missing piece is retrieval-time graph expansion. Current retrieval can fetch parent chunks and ordinary textual references, but it does not consistently follow table-specific metadata edges.

## Goals

- When a table chunk is retrieved, assemble evidence that includes both the table data and its textual interpretation.
- Prefer deterministic graph edges before heuristic proximity.
- Keep expansion bounded, deduplicated, and traceable.
- Make the behavior testable with fake chunk stores and real parsed paper artifacts.

## Non-Goals

- Rebuilding table extraction or Surya layout detection.
- Adding LLM-based table reasoning during retrieval.
- Adding image embeddings or multimodal reranking.
- Changing persistent chunk payload schemas.

## Proposed Flow

1. Base retrieval returns top chunks using the existing text/vector/visual fusion path.
2. For each retrieved table chunk, build a table expansion set:
   - `nearby_context_chunk_id`
   - `referenced_by_chunks[*].chunk_id`
   - `parent_chunk_id`
   - `parent_table_chunk_id` when the hit is a row-group chunk
3. Fetch those chunks from the chunk store.
4. Add result-oriented context:
   - same paper only
   - prefer chunks with section roles or titles matching experiment, result, analysis, conclusion, ablation, evaluation
   - prefer same section, adjacent section, or referenced section before broader paper-level context
5. Deduplicate by `chunk_id`.
6. Attach retrieval metadata:
   - `expanded_from_chunk_id`
   - `expansion_reason`
   - `expansion_edge`
   - `expansion_rank`
7. Return evidence in a bounded order:
   - original hit
   - nearby context
   - explicit referencing paragraphs
   - parent/row-group context
   - role-prioritized result/conclusion context

## Ranking Policy

V1 should use deterministic ordering instead of a new reranker:

1. Direct retrieved table chunk
2. Explicit `referenced_by_chunks`
3. `nearby_context_chunk_id`
4. `parent_chunk_id` / `parent_table_chunk_id`
5. Role-prioritized result/conclusion chunks

The expansion should use a small budget, for example `max_table_context_chunks=4`, so a single table does not flood the prompt.

## Failure Modes

- If a table has no references, still include nearby/parent context.
- If references point to missing chunks, skip them and record no broken evidence.
- If the query is not table/result oriented, avoid broad table expansion unless a table chunk is already in the top results.
- If multiple tables are retrieved, apply budget per table and global evidence budget.

## Open Questions

- Should `result` become a first-class `SectionRole`, or should V1 infer it from title keywords while keeping the existing role enum?
- Should table expansion run only for `table_query`, or also for `numerical_result`, `comparison`, and result-oriented natural language queries?
- Should conclusion expansion be same-section/nearby only in V1 to avoid pulling generic conclusion text?
