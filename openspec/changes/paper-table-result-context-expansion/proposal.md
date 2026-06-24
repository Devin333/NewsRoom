## Why

Research RAG can already emit table chunks with caption, rows, visual region metadata, nearby context, and explicit body references. However, retrieval currently relies mostly on the directly retrieved chunks, parent chunks, and normal textual references. When a user asks a result-oriented question such as "what do the experimental results show?", a table chunk alone may not include the conclusion/result paragraph that interprets the numbers.

## What Changes

- Add table evidence expansion after retrieval: when a table chunk is selected, also fetch its `nearby_context_chunk_id`, `referenced_by_chunks`, and relevant parent/table-row-group context.
- Prioritize result-bearing paragraphs by section role and section title, especially `experiment`, `analysis`, and `conclusion`.
- Deduplicate expanded evidence and annotate why each context chunk was included.
- Keep table parsing, OCR, image cropping, and table chunk creation unchanged.

## Capabilities

### New Capabilities
- `paper-table-result-context-expansion`: Defines table-to-result-paragraph evidence expansion for research paper RAG.

### Modified Capabilities
- `research-runtime`: Research retrieval must be able to expand table evidence into nearby, referenced, and result/conclusion context chunks.

## Impact

- Likely affects `business/research/rag/retriever.py`, retrieval policy tests, and table chunk retrieval tests.
- Uses existing chunk metadata: `nearby_context_chunk_id`, `referenced_by_chunks`, `parent_chunk_id`, `parent_table_chunk_id`, `is_table_row_group`, and paragraph `visual_references`.
- No parser, database schema, or vector schema migration is required for V1.
