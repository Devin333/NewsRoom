## Context

Current parent expansion is deterministic and simple: for each returned child chunk, fetch `parent_chunk_id`, deduplicate by parent id, and return the full parent chunk. If no parent exists, return the child itself as fallback. This gives the LLM section-level context, but it does not distinguish a short useful parent from a long noisy one.

## Goals

- Keep parent context available for questions that need section-level explanation.
- Bound parent expansion independently from child retrieval.
- Avoid returning full long sections when a child-local snippet is enough.
- Let reranking suppress weak parent context without breaking deterministic fallback behavior.
- Preserve traceability from snippets back to the original parent and matched child.

## Non-Goals

- Changing chunk creation, section splitting, parser output, or persistent storage schema.
- Replacing child retrieval or table-context expansion.
- Requiring a reranker to be available in all environments.

## Proposed Flow

1. Base retrieval returns child chunks using the existing text/vector/visual path.
2. Parent expansion builds candidates from each child with `parent_chunk_id`.
3. Parent candidates are deduplicated by parent id while retaining the best child anchor.
4. Apply an intent-specific parent policy:
   - `concept_method`, `contribution`, and broad explanatory questions get a larger parent budget.
   - `table_query`, `formula_query`, and factual/numerical result questions get a smaller parent budget.
   - unknown intents use the default budget.
5. If a parent exceeds the long-parent threshold, return a child-anchored snippet with metadata pointing to the original parent.
6. If a reranker exists, score parent candidates with a query composed of the user question and child anchor content.
7. Enforce count and approximate token budgets after rerank/deterministic ordering.
8. If no parent candidates are available, keep the existing fallback of returning children themselves.

## Parent Budget Policy

The policy should expose tunables:

- `max_parent_chunks`
- `max_parent_tokens`
- `long_parent_token_threshold`
- `parent_snippet_token_window`
- `parent_rerank_score_threshold`
- `parent_intent_budgets`

Token counts can use a lightweight approximate estimator in retrieval because this is a budget guard, not a billing meter.

## Snippet Strategy

When parent content is too long:

1. Prefer locating the child content inside the parent content.
2. If the child anchor is found, crop a window around it.
3. If not found, fall back to the first window of parent content.
4. Preserve the original `chunk_id` for dedupe stability and record:
   - `parent_snippet=true`
   - `source_parent_chunk_id`
   - `parent_anchor_child_id`
   - `parent_snippet_strategy`
   - `parent_original_token_estimate`

## Rerank Strategy

Reranking applies only to parent candidates, not child hits. If reranker scoring fails or returns malformed output, retrieval falls back to deterministic candidate order. Parent rerank scores should be recorded in metadata when available:

- `parent_rerank_score`
- `parent_rerank_strategy`
- `parent_rerank_query`

## Failure Modes

- If every reranked parent is below threshold, keep the strongest deterministic parent so evidence is not emptied accidentally.
- If a parent chunk is missing, skip it without failing retrieval.
- If snippet extraction cannot find an anchor, use a deterministic leading snippet.
- If budget is exhausted, keep earlier/higher-ranked parent candidates and record budget metrics in retrieval metadata.
